"""Package defining a superclass with methods common to Clients and Servers.

This is where the real work gets done.
"""

from asyncio import (
    AbstractEventLoop,
    CancelledError,
    Future,
    gather,
    IncompleteReadError,
    Queue,
    StreamReader,
    StreamWriter,
    Task,
    TimeoutError,
    wait_for,
)
from collections import Counter
from datetime import datetime as dt
from functools import partial
from itertools import chain
from json import JSONDecodeError, loads
from typing import Any, Callable, Dict, List, overload, TypeVar, Union
from uuid import uuid4

from ..util.output import (
    echo,
    err as err_,
    hl_method,
    hl_remote,
    hl_rtype,
    res_bad,
    res_good,
    warn,
)
from .connection import can_encrypt, Connection
from .exc import RemoteError
from .handlers import rpc_response, request_handler, response_handler
from .protocol import (
    Error,
    JRPC,
    Message,
    Notification,
    Request,
    Response,
)


counter = lambda: Counter(byte=0, notif=0, request=0, response=0)
TV = TypeVar("TV", bound=Callable)


def mkid(remote: "Remote") -> str:
    return format(
        (uuid4().int + remote.port + sum(map(int, remote.addr.split(".")))) % 0x1000,
        "0>3X",
    )


class Remote:
    """An abstraction representing the other end of some connection, as well as
    the connection itself, to a point.

    Initialized with an Async Event Loop, and the Reader and Writer of a Stream,
    the Remote class provides a clean interface for reception and transmission
    of data to a Remote Host.
    """

    __slots__ = (
        "eventloop",
        "instr",
        "outstr",
        "connection",
        "addr",
        "port",
        "hooks_notif",
        "hooks_notif_inher",
        "hooks_request",
        "hooks_request_inher",
        "futures",
        "lines",
        "total_sent",
        "total_recv",
        "group",
        "rtype",
        "id",
        "opened",
        "startup",
    )

    def __init__(
        self,
        eventloop: AbstractEventLoop,
        instr: StreamReader,
        outstr: StreamWriter,
        group: set = None,
        *,
        rtype: str = "Remote",
        remote_id: str = None,
    ):
        self.eventloop: AbstractEventLoop = eventloop
        self.instr: StreamReader = instr
        self.outstr: StreamWriter = outstr
        self.connection: Connection = Connection(instr, outstr)

        ap = self.outstr.get_extra_info("peername", ("0.0.0.0", 0))
        self.addr: str = ap[0]
        self.port: int = ap[1]

        self.hooks_notif: Dict[str, Callable] = {}
        self.hooks_notif_inher: Dict[str, Callable] = {}

        self.hooks_request: Dict[str, Callable] = {}
        self.hooks_request_inher: Dict[str, Callable] = {}

        self.futures: Dict[str, Future] = {}

        self.lines: Queue = Queue()
        self.total_sent: Counter = counter()
        self.total_recv: Counter = counter()

        self.group: set = group
        self.rtype: str = rtype
        self.id: str = remote_id or mkid(self)

        now = dt.utcnow()
        self.opened: dt = now
        self.startup: dt = now
        self._add_hooks()

    @property
    def host(self) -> str:
        return f"{self.addr}:{self.port}"

    @property
    def is_secure(self) -> bool:
        return bool(self.connection.can_encrypt and self.connection.encrypted)

    @property
    def open(self) -> bool:
        return self.connection.open

    def __repr__(self) -> str:
        return f"{self.rtype} {self.id}"

    def __str__(self) -> str:
        return hl_rtype(f"{self.rtype} {hl_remote(self.id)}")

    def _add_hooks(self) -> None:
        """Add the initial hooks for the connection: Ping, and the two hooks
            required for an RSA Key Exchange.
        """

        @self.handle_request("PING")
        def cb_ping(data: dict, _remote: Remote) -> rpc_response:
            return data.get("params", [])

        @self.handle_request("RSA.EXCH")
        async def cb_rsa_exchange(data: dict, remote: Remote) -> rpc_response:
            if remote.connection.can_encrypt:
                echo(
                    "info",
                    [
                        "Receiving request for Secure Connection. Sending Key.",
                        "(The connection is not encrypted yet.)",
                    ],
                )
                remote.connection.add_keys(*data.get("params", [None, None]))
                return remote.connection.keys
            else:
                err_("Cannot establish a Secure Connection.")
                return 92, "Encryption Unavailable"

        @self.handle_request("RSA.CONF")
        async def cb_rsa_confirm(data: dict, remote: Remote) -> rpc_response:
            if remote.connection.encryption_ready():
                await remote.respond(data["id"], data["method"], res=[True])
                remote.connection.begin_encryption()
                echo("win", "Connection Secured by RSA Key Exchange.")
            else:
                return 1, "Cannot Activate"

    async def enable_rsa(self) -> bool:
        if not self.connection.can_encrypt:
            warn("Cannot enable RSA: Encryption is not available.")
            return False
        elif self.connection.encrypted:
            warn("Cannot enable RSA: Encryption is already in progress.")
            return False
        else:
            # Ask the remote Host for its Public Key, while providing our own.
            remote_pub, remote_ver = await self.request_wait(
                "RSA.EXCH", self.connection.keys, [None, None]
            )

            if remote_pub and remote_ver:
                self.connection.add_keys(remote_pub, remote_ver)
            else:
                return False

            # Double check that the remote Host is ready to start encrypting.
            if (await self.request_wait("RSA.CONF", [True], [False]))[0]:
                # We can now start using encryption.
                self.connection.begin_encryption()
                return True
            else:
                # Something went wrong. Do NOT switch to encryption.
                return False

    async def process_message(self, data: dict, tasks: List[Task]) -> None:
        """A set of data has been received. If it is a Response, get the Future
        waiting for it and set its Result. Otherwise, find a Hook waiting for
        the Method received, and run it.
        """
        method = data.get("method")
        mid = data.get("id")
        mtype = JRPC.check(data)

        if mtype is JRPC.RESPONSE:
            # Message is a RESPONSE.
            self.total_recv["response"] += 1
            if mid in self.futures:
                # Something is waiting for this message.
                future: Future = self.futures.pop(mid)

                if future.cancelled():
                    warn(
                        f"Received a Response from {self!r} for a cancelled Future."
                        f" UUID: {mid}"
                    )
                elif future.done():
                    warn(
                        f"Received a Response from {self!r} for a closed Future."
                        f" UUID: {mid}"
                    )
                else:
                    # We need to fulfill this Future now.
                    echo("recv", f"Receiving a Response from {self}.")

                    if "error" in data:
                        # Server sent an Error Response. Forward it to the Future.
                        future.set_exception(RemoteError.from_message(data))
                    else:
                        # Server sent a Result Response. Give it to the Future.
                        future.set_result(data["result"])
            else:
                # Nothing is waiting for this message. Make a note and move on.
                warn(f"Received an unsolicited Response for {self!r}. UUID: {mid}")

        elif mtype is JRPC.REQUEST:
            # Message is a REQUEST.
            self.total_recv["request"] += 1

            hooks = self.hooks_request.copy()
            hooks.update(self.hooks_request_inher)

            if method in hooks:
                # We know where to send this type of Request.
                echo("recv", f"Receiving {hl_method(method)} Request from {self}.")
                tasks.append(self.eventloop.create_task(hooks[method](data, self)))
            else:
                # We have no hook for this method; Return an Error.
                warn(f"Receiving invalid {method} Request from {self!r}.")
                await self.respond(mid, err=Error.method_not_found(method))

        elif mtype is JRPC.NOTIF:
            # Message is a NOTIFICATION.
            self.total_recv["notif"] += 1

            hooks = self.hooks_notif.copy()
            hooks.update(self.hooks_notif_inher)

            if method == "TERM":
                # The connection is being explicitly terminated.
                echo("recv", f"Receiving TERMINATE from {self}.")
                raise ConnectionResetError(
                    data["params"]["reason"] or "Connection terminated by peer."
                )
            elif method in hooks:
                # We know where to send this type of Notification.
                echo("recv", f"Receiving {hl_method(method)} Notification from {self}.")
                tasks.append(self.eventloop.create_task(hooks[method](data, self)))
            else:
                # We have no hook for this method; Return an Error.
                warn(f"Receiving invalid {method} Notification from {self!r}.")
                await self.respond(mid, err=Error.method_not_found(method))

        else:
            # Message is not a valid JSON-RPC structure. If we can find an ID,
            #   send a Response containing an Error and a frowny face.
            err_(f"Received an invalid Message from {self}.")
            if mid:
                await self.respond(mid, err=Error.invalid_request(list(data.keys())))

    def handle_request(self, method: str) -> Callable:
        return request_handler(self, method)

    def handle_response(self, **kw) -> Callable:
        return response_handler(self, **kw)

    @overload
    def hook_notif(self, method: str) -> Callable[[TV], TV]:
        ...

    @overload
    def hook_notif(self, method: str, func: TV) -> TV:
        ...

    def hook_notif(self, method: str, func=None):
        """Signal to the Remote that `func` is waiting for Notifications of the
            provided `method` value.

        The provided Function should take two arguments: The first is the Data
            of the Notification, and the second is the Remote.
        """
        if func is not None:
            # Function provided. Hook it directly.
            self.hooks_notif[method] = func
        else:
            # Function NOT provided. Return a Decorator.
            def hook(func_):
                self.hooks_notif[method] = func_
                return func_

            return hook

    @overload
    def hook_request(self, method: str) -> Callable[[TV], TV]:
        ...

    @overload
    def hook_request(self, method: str, func: TV) -> TV:
        ...

    def hook_request(self, method: str, func=None) -> Callable:
        """Signal to the Remote that `func` is waiting for Requests of the
            provided `method` value.

        The provided Function should take two arguments: The first is the Data
            of the Request, and the second is the Remote.
        """
        if func is not None:
            # Function provided. Hook it directly.
            self.hooks_request[method] = func
        else:
            # Function NOT provided. Return a Decorator.
            def hook(func_):
                self.hooks_request[method] = func_
                return func_

            return hook

    def close(self) -> None:
        self.total_recv["byte"] = self.connection.total_recv
        self.total_sent["byte"] = self.connection.total_sent
        self.connection.close()

        if self.group is not None and self in self.group:
            # Remove self from Client Set, if possible.
            self.group.remove(self)

    async def run_helpers(self, count: int) -> None:
        """Spawn and manage Helper Tasks."""
        helpers: List[Task] = []

        async def _helper():
            """Repeatedly, forever, read a line from the Input Queue and put it
                through the Processor. Provide a List to be filled with Tasks.
                Then, when the Processing Coroutine finishes, Gather and Await
                all the Tasks, if any, that have since accrued.
            """
            while line := await self.lines.get():
                try:
                    data = loads(line)

                except JSONDecodeError as e:
                    warn(f"Invalid JSON received from {self!r}.")
                    await self.respond("0", err=Error.parse_error(str(e)))
                except UnicodeDecodeError:
                    warn(f"Corrupt data received from {self!r}.")

                ## TODO: Does this catch still matter?
                # except ConnectionError as e:
                #     # Whatever just happened was too much to just die calmly. Close
                #     #   down the entire Remote.
                #     if self.open:
                #         self.close()
                #         echo("dcon", f"Connection with {self} closed: {e}")

                else:
                    if isinstance(data, dict):
                        data = [data]

                    tasks: List[List[Task]] = [[] for _ in data]

                    await gather(
                        *(map(self.process_message, data, tasks)),
                        return_exceptions=True,
                    )
                    await gather(*chain(*tasks), return_exceptions=True)

                finally:
                    self.lines.task_done()

        new = lambda: self.eventloop.create_task(_helper())

        def revive():
            for i, h in enumerate(helpers):
                if h.done():
                    # Replace all Helpers that have stopped.
                    e = h.exception()
                    if e is None:
                        err_(f"A Helper Task in {self!r} has died.")
                    else:
                        err_(f"A Helper Task in {self!r} has died to an Exception:", e)
                    helpers[i] = new()

        try:
            # Create Tasks.
            for _ in range(count):
                helpers.append(new())

            # Loop "forever", waiting for one to Raise. Note that we do NOT pass
            #   ``return_exceptions`` to these ``gather()``s.
            while True:
                try:
                    await gather(*helpers)
                except CancelledError:
                    # If this is Cancelled, break the loop and stop all Helpers.
                    break
                except:
                    # On any other Exception, ignore it and revive dead Helpers.
                    revive()
        finally:
            # Kill Tasks.
            g = gather(*helpers)

            if g.cancel():
                await g

    async def loop(self, helper_count: int = 5) -> None:
        """Listen on the Connection, and write data from it into the Queue to be
        handled by Helper Tasks.
        """
        # Create a Task that creates Tasks.
        helper_runner = self.eventloop.create_task(self.run_helpers(helper_count))

        try:
            async for item in self.connection:
                # Receive text from the Input Stream.
                if isinstance(item, Exception):
                    # If we received an Exception, the Decryption failed.
                    warn(f"Decryption from {self!r} failed:", item)
                else:
                    # Otherwise, add it to the Queue.
                    await self.lines.put(item)

                # Double check that we are still listening.
                if helper_runner.done():
                    # Helper Helper has ended, for some reason.
                    e = helper_runner.exception()
                    if e:
                        raise e
                    else:
                        break

        except IncompleteReadError:
            if self.open:
                err_(f"Connection with {self!r} cut off.")
        except EOFError:
            if self.open:
                err_(f"Connection with {self!r} failed: Stream ended.")
        except ConnectionError as e:
            if self.open:
                echo("dcon", f"Connection with {self} closed: {e}")
        except CancelledError:
            if self.open:
                err_(f"Listening to {self!r} was cancelled.")
        except Exception as e:
            if self.open:
                err_(f"Connection with {self!r} failed:", e)

        finally:
            self.close()
            if not helper_runner.done():
                helper_runner.cancel()
                await helper_runner

    async def notif(
        self,
        meth: str,
        params: Union[dict, list, tuple] = None,
        nohandle: bool = False,
        quiet: bool = False,
    ) -> None:
        """Assemble and send a JSON-RPC Notification with the given data."""
        if not self.open:
            return

        if not quiet:
            echo("send", f"Sending {hl_method(meth)} Notification to {self}.")

        try:
            self.total_sent["notif"] += 1
            if isinstance(params, dict):
                await self.send(Notification(meth, **params))
            elif isinstance(params, (list, tuple)):
                await self.send(Notification(meth, *params))
            else:
                await self.send(Notification(meth))
        except Exception as e:
            err_("Failed to send Notification:", e)
            if nohandle:
                raise e

    async def request(
        self,
        meth: str,
        params: Union[dict, list, tuple] = None,
        *,
        callback: Callable = None,
        nohandle: bool = False,
        timeout: float = 0,
        quiet: bool = False,
    ) -> Future:
        """Assemble a JSON-RPC Request with the given data. Send the Request,
            and return a Future to represent the eventual result.
        """
        # Create a Future which will represent the Response.
        future: Future = self.eventloop.create_future()

        if not self.open:
            future.set_exception(ConnectionResetError)
            return future

        if not quiet:
            echo("send", f"Sending {hl_method(meth)} Request to {self}.")
        self.total_sent["request"] += 1

        if isinstance(params, dict):
            req = Request(meth, **params)
        elif isinstance(params, (list, tuple)):
            req = Request(meth, *params)
        else:
            req = Request(meth)

        self.futures[req.id] = future

        if callback:
            cb = partial(callback, remote=self)
            # noinspection PyTypeChecker
            future.add_done_callback(cb)

        try:
            await self.send(req)
        except Exception as e:
            err_("Failed to send Request:", e)
            if nohandle:
                raise e
        finally:
            if timeout > 0:
                return wait_for(future, timeout)
            else:
                return future

    async def request_wait(
        self,
        meth: str,
        params: Union[dict, list, tuple] = None,
        default: Any = None,
        *,
        callback: Callable = None,
        nohandle: bool = False,
        timeout: float = 10,
        raise_remote_err: bool = False,
    ) -> Any:
        """Send a JSON-RPC Request with the given data, the same as
            `Remote.request()`. However, rather than return the Future, handle
            it, and return None if the request timed out or (unless specified)
            yielded an Error Response.
        """
        if self.open:
            future = await self.request(
                meth, params, callback=callback, nohandle=nohandle
            )
            try:
                if timeout > 0:
                    await wait_for(future, timeout)
                else:
                    await future

            except RemoteError as e:
                if raise_remote_err:
                    raise e
                else:
                    return default
            except (CancelledError, TimeoutError):
                warn(f"{meth} Request timed out.")
                return default

            else:
                return future.result()

    async def respond(
        self,
        mid: str,
        method: str = None,
        *,
        err: Error = None,
        res: Union[dict, list, tuple] = None,
        nohandle: bool = False,
    ) -> None:
        if self.open:
            echo(
                "send",
                "Sending {} Response{} to {}.".format(
                    res_bad("Error") if err else res_good("Result"),
                    f" for {hl_method(method)}" if method else "",
                    self,
                ),
            )
            self.total_sent["response"] += 1
            try:
                await self.send(
                    Response(mid, error=err) if err else Response(mid, result=res)
                )
            except Exception as e:
                # noinspection PyCallingNonCallable
                err_("Failed to send Response:", e)
                if nohandle:
                    raise e

    async def send(self, msg: Message) -> None:
        if self.open:
            await self.connection.write(str(msg))

    async def terminate(self, reason: str = None) -> None:
        if self.open:
            try:
                await self.notif("TERM", {"reason": reason}, nohandle=True)
            except Exception as e:
                err_("Failed to send TERM:", e)
            finally:
                self.close()
