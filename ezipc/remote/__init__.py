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
    wait_for,
)
from collections import Counter
from datetime import datetime as dt
from functools import partial
from inspect import isawaitable
from json import JSONDecodeError
from secrets import randbits
from typing import (
    AsyncGenerator,
    Awaitable,
    Callable,
    Dict,
    Generator,
    List,
    Optional,
    overload,
    TypeVar,
    Union,
)
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
from .handlers import rpc_response, notif_handler, request_handler, response_handler
from .protocol import (
    Batch,
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

        @self.hook_request("PING")
        def cb_ping(data):
            return data

        @self.hook_request("RSA.EXCH")
        async def cb_rsa_exchange(data: list):
            if self.connection.can_encrypt:
                echo(
                    "info", "Receiving request for Secure Connection. Sending Key.",
                )
                self.connection.add_keys(*data)
                return self.connection.keys
            else:
                err_("Cannot establish a Secure Connection.")
                return Error(92, "Encryption Unavailable")

        @self.hook_request("RSA.CONF")
        def cb_rsa_confirm(_data):
            if self.connection.encryption_ready():
                yield [True]
                self.connection.begin_encryption()
                echo("win", "Connection Secured by RSA Key Exchange.")
            else:
                yield Error(1, "Cannot Activate")

    def _id_new(self) -> str:
        return f"{self.id}/{randbits(24):0>6X}"

    async def enable_rsa(self) -> bool:
        if not self.connection.can_encrypt:
            warn("Cannot enable RSA: Encryption is not available.")
            return False
        elif self.connection.encrypted:
            warn("Cannot enable RSA: Encryption is already in progress.")
            return False
        else:
            # Ask the remote Host for its Public Key, while providing our own.
            remote_pub, remote_ver = await self.request(
                "RSA.EXCH", self.connection.keys, timeout=10
            )

            if remote_pub and remote_ver:
                self.connection.add_keys(remote_pub, remote_ver)
            else:
                return False

            # Double check that the remote Host is ready to start encrypting.
            try:
                await self.request("RSA.CONF", [True], timeout=10)
            except:
                # Something went wrong. Do NOT switch to encryption.
                return False
            else:
                # We can now start using encryption.
                self.connection.begin_encryption()
                return True

    def process_message(self, msg: Message) -> Optional[Union[Exception, Response]]:
        """A set of data has been received. If it is a Response, get the Future
        waiting for it and set its Result. Otherwise, find a Hook waiting for
        the Method received, and run it.
        """
        if isinstance(msg, Response):
            # Message is a RESPONSE.
            self.total_recv["response"] += 1
            if msg.id in self.futures:
                # Something is waiting for this message.
                future: Future = self.futures.pop(msg.id)

                if future.cancelled():
                    warn(
                        f"Received a Response from {self!r} for a cancelled Future."
                        f" UUID: {msg.id}"
                    )
                elif future.done():
                    warn(
                        f"Received a Response from {self!r} for a closed Future."
                        f" UUID: {msg.id}"
                    )
                else:
                    # We need to fulfill this Future now.
                    echo("recv", f"Receiving a Response from {self}.")

                    if msg.error:
                        # Server sent an Error Response. Forward it to the Future.
                        future.set_exception(msg.error.as_exception())
                    else:
                        # Server sent a Result Response. Give it to the Future.
                        future.set_result(msg.result)
            else:
                # Nothing is waiting for this message. Make a note and move on.
                warn(f"Received an unsolicited Response for {self!r}. UUID: {msg.id}")

        elif isinstance(msg, Request):
            # Message is a REQUEST.
            self.total_recv["request"] += 1

            hooks = self.hooks_request.copy()
            hooks.update(self.hooks_request_inher)

            if msg.method in hooks:
                # We know where to send this type of Request.
                echo("recv", f"Receiving {hl_method(msg.method)} Request from {self}.")
                try:
                    return hooks[msg.method](msg, self)
                except Exception as e:
                    warn(f"Unknown Error on {msg.method!r} Request from {self!r}:", e)
                    return e
            else:
                # We have no hook for this method; Return an Error.
                warn(f"Receiving invalid {msg.method} Request from {self!r}.")
                return msg.response(error=Error.method_not_found(msg.method))

        elif isinstance(msg, Notification):
            # Message is a NOTIFICATION.
            self.total_recv["notif"] += 1

            hooks = self.hooks_notif.copy()
            hooks.update(self.hooks_notif_inher)

            if msg.method == "TERM":
                # The connection is being explicitly terminated.
                echo("recv", f"Receiving TERMINATE from {self}.")
                raise ConnectionResetError(
                    msg.params["reason"] or "Connection terminated by peer."
                )
            elif msg.method in hooks:
                # We know where to send this type of Notification.
                echo(
                    "recv",
                    f"Receiving {hl_method(msg.method)} Notification from {self}.",
                )
                try:
                    return hooks[msg.method](msg, self)
                except Exception as e:
                    warn(
                        f"Unknown Error on {msg.method!r} Notification from {self!r}:",
                        e,
                    )
                    return e
            else:
                # We have no hook for this method; Return an Error.
                warn(f"Receiving invalid {msg.method} Notification from {self!r}.")
                # return Response(msg, error=Error.method_not_found(msg.method))

        # else:
        #     # Message is not a valid JSON-RPC structure. If we can find an ID,
        #     #   send a Response containing an Error and a frowny face.
        #     err_(f"Received an invalid Message from {self}.")
        #     if msg.id:
        #         return Response(
        #             msg, error=Error.invalid_request(list(dict(msg).keys()))
        #         )

    def hook_notif(self, method: str):
        """Signal to the Remote that `func` is waiting for Notifications of the
            provided `method` value.

        The provided Function should take two arguments: The first is the Data
            of the Notification, and the second is the Remote.
        """
        return notif_handler(self.hooks_notif, method)

    def hook_request(self, method: str) -> Callable:
        """Signal to the Remote that `func` is waiting for Requests of the
            provided `method` value.

        The provided Function should take two arguments: The first is the Data
            of the Request, and the second is the Remote.
        """
        return request_handler(self.hooks_request, method)

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
                    data = {
                        msg: self.process_message(msg) for msg in (JRPC.decode(line))
                    }

                except JSONDecodeError as e:
                    warn(f"Invalid JSON received from {self!r}.")
                    await self.respond(None, err=Error.parse_error(str(e)))
                except UnicodeDecodeError:
                    warn(f"Corrupt data received from {self!r}.")

                except CancelledError:
                    raise

                except ConnectionError as e:
                    # Whatever just happened was too much to just die calmly.
                    #   Close down the entire Remote.
                    if self.open:
                        self.close()
                        echo("dcon", f"Connection with {self} closed: {e}")

                except Exception as e:
                    err_("Unknown Exception:", e)
                    raise e

                else:
                    responses: Batch = Batch()
                    tasks: Dict[Message, Awaitable] = {}

                    for recv, tsk in data.items():
                        # Loop through the Processors of all Data received.
                        if isinstance(tsk, Response):
                            # If the Processor returned a Response, add it to
                            #   the Batch.
                            responses.append(tsk)

                        elif isinstance(tsk, (dict, list, tuple)):
                            # If the Processor returned something that can be
                            #   made into a Response, do it and add it.
                            if isinstance(recv, Request):
                                responses.append(recv.response(result=tsk))

                        elif isinstance(tsk, Exception):
                            # If it returned an Exception, wrap it in an Error
                            #   and add it.
                            if isinstance(recv, Request):
                                responses.append(
                                    recv.response(error=Error.from_exception(tsk))
                                )

                        elif isawaitable(tsk):
                            # If it can be Awaited, add it as a Task.
                            tasks[recv] = tsk

                        elif isinstance(tsk, AsyncGenerator):
                            # If it is an Async Generator, this means that the
                            #   Processor will Yield something, and then it has
                            #   some cleanup afterwards. Add the ANext as a
                            #   Task.
                            tasks[recv] = tsk.__anext__()

                        elif isinstance(tsk, Generator):
                            # If it is a Sync Generator, same deal; However, it
                            #   must be wrapped in a Task first.
                            async def _n():
                                return next(tsk)

                            tasks[recv] = _n()

                        elif isinstance(recv, Request):
                            # Anything else is wrapped within a List.
                            responses.append(
                                recv.response(result=[] if tsk is None else [tsk])
                            )

                    # Gather and Await all the Tasks.
                    finals = dict(
                        zip(
                            tasks.keys(),
                            await gather(*tasks.values(), return_exceptions=True),
                        )
                    )

                    for recv, ret in finals.items():
                        # Add the Responses of the Tasks to the Batch.
                        if isinstance(ret, Response):
                            # All native Responses are added directly.
                            responses.append(ret)

                        elif isinstance(ret, (dict, list, tuple)):
                            # Structures are wrapped and Added...IF the original
                            #   Message was a Request.
                            if isinstance(recv, Request):
                                responses.append(recv.response(result=ret))

                        elif isinstance(ret, Exception):
                            # Exceptions are again wrapped in Errors.
                            if isinstance(recv, Request):
                                responses.append(
                                    recv.response(error=Error.from_exception(ret))
                                )

                        elif isinstance(recv, Request):
                            # Anything else is wrapped within a List.
                            responses.append(
                                recv.response(result=[] if ret is None else [ret])
                            )

                    # # # SEND THE BATCH # # #
                    if responses:
                        await self.send_batch(responses)
                    # # # ============== # # #

                    # Now, handle any Cleanup required by Generators.
                    for original in data.values():
                        if isinstance(original, AsyncGenerator):
                            async for _ in original:
                                pass
                        elif isinstance(original, Generator):
                            for _ in original:
                                pass

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
            g = gather(*helpers, return_exceptions=True)

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
            if helper_runner.cancel():
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

    @overload
    async def request(
        self,
        meth: str,
        params: Union[dict, list, tuple] = None,
        *,
        callback: Callable = None,
        nohandle: bool = False,
        quiet: bool = False,
    ) -> Future:
        ...

    @overload
    async def request(
        self,
        meth: str,
        params: Union[dict, list, tuple] = None,
        *,
        callback: Callable = None,
        nohandle: bool = False,
        quiet: bool = False,
        timeout: float,
    ) -> Union[dict, list]:
        ...

    async def request(
        self,
        meth: str,
        params: Union[dict, list, tuple] = None,
        *,
        callback: Callable = None,
        nohandle: bool = False,
        quiet: bool = False,
        timeout: float = 0,
    ) -> Union[Union[dict, list], Future]:
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
            req = Request(meth, **params, mid=self._id_new())
        elif isinstance(params, (list, tuple)):
            req = Request(meth, *params, mid=self._id_new())
        else:
            req = Request(meth, mid=self._id_new())

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
                return await wait_for(future, timeout)
            else:
                return future

    async def respond(
        self,
        mid: Optional[str],
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

    async def send(self, msg: Message) -> int:
        if self.open:
            return await self.connection.write(str(msg))
        else:
            return 0

    async def send_batch(self, batch: Batch) -> int:
        if batch and self.open:
            return await self.connection.write(batch.json())
        else:
            return 0

    async def terminate(self, reason: str = None) -> None:
        if self.open:
            try:
                await self.notif("TERM", {"reason": reason}, nohandle=True)
            except Exception as e:
                err_("Failed to send TERM:", e)
            finally:
                self.close()
