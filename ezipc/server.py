from asyncio import (
    AbstractEventLoop,
    AbstractServer,
    CancelledError,
    gather,
    get_event_loop,
    run,
    start_server,
    StreamReader,
    StreamWriter,
    Task,
    TimeoutError,
    wait_for,
)
from collections import Counter, MutableSet
from datetime import datetime as dt
from functools import partial, wraps
from inspect import signature
from socket import AF_INET, SOCK_DGRAM, socket
from typing import Callable, Dict, Optional, overload, Union

from .remote import (
    can_encrypt,
    counter,
    Remote,
    RemoteError,
    request_handler,
    rpc_response,
    TV,
)
from .util import callback_response, echo, err, P, warn


__all__ = (
    "callback_response",
    "can_encrypt",
    "echo",
    "err",
    "rpc_response",
    "P",
    "Remote",
    "RemoteError",
    "request_handler",
    "Server",
    "warn",
)


class Server:
    """The Server is the component of the Client/Server Model that waits for
    input from a Client, and then operates on it. The Server can interface with
    multiple Clients at the same time, and may even facilitate communications
    between two Clients.

    As the more passive component, the Server will spend most of its time
    waiting for Clients.

    :param str addr: IPv4 Address to listen on. If this is not supplied, and
        ``autopublish`` is not `True`, ``127.0.0.1`` will be used.
    :param int port: IP Port to listen on.
    :param bool autopublish: If this is `True`, the Server will try to
        automatically discover the Network Address of the local system. If it
        cannot be found, ``addr`` will be used as a fallback.
    :param int helpers: The number of Helper Tasks to be used by **each**
        Remote. More Helpers can be useful when receiving prompts to perform
        very await-heavy procedures, such as multiple file transfers, but when
        not in use they mostly sap memory.
    """

    __slots__ = (
        "addr",
        "port",
        "eventloop",
        "helpers",
        "listeners",
        "remotes",
        "server",
        "startup",
        "total_clients",
        "total_sent",
        "total_recv",
        "hooks_notif",
        "hooks_request",
        "hooks_connection",
    )

    def __init__(
        self,
        addr: str = "",
        port: int = 9002,
        autopublish: bool = False,
        helpers: int = 5,
    ):
        if autopublish:
            # Override the passed parameter and try to autofind the address.
            sock = socket(AF_INET, SOCK_DGRAM)
            try:
                sock.connect(("10.255.255.255", 1))
                addr = sock.getsockname()[0]
            except (InterruptedError, OSError):
                warn("Failed to autoconfigure IP address.")
            finally:
                sock.close()

        if not addr:
            # No Address specified, and autoconfig failed or was not enabled;
            #   Fall back to localhost.
            addr = "127.0.0.1"

        self.addr: str = addr
        self.port: int = port
        self.helpers: int = helpers

        self.eventloop: Optional[AbstractEventLoop] = None
        self.listeners: MutableSet[Task] = set()
        self.remotes: MutableSet[Remote] = set()
        self.server: Optional[AbstractServer] = None
        self.startup: dt = dt.utcnow()

        self.total_clients: int = 0
        self.total_sent: Counter = counter()
        self.total_recv: Counter = counter()

        self.hooks_notif = {}
        self.hooks_request = {}
        self.hooks_connection = [self.encrypt_remote]

    def setup(self, *_a, **_kw):
        """Execute all prerequisites to running, before running. Meant to be
            overwritten by Subclasses.
        """

        @self.hook_request("TIME")
        async def cb_time(_, remote: Remote):
            return {"startup": self.startup.timestamp(), "id": remote.id}

    @overload
    def hook_notif(self, method: str) -> Callable[[TV], TV]:
        ...

    @overload
    def hook_notif(self, method: str, func: TV) -> TV:
        ...

    def hook_notif(self, method: str, func=None):
        """Signal to the Remote that `func` is waiting for Notifications of the
            provided `method` value.
        """
        if func is None:
            # Function NOT provided. Return a Decorator.
            return partial(self.hook_notif, method)
        else:
            # Function provided. Hook it directly.
            @wraps(func)
            async def handler(data: dict, _conn: Remote):
                try:
                    await func(data.get("params", None))
                except Exception as e:
                    err(f"Notification raised Exception:", e)

            self.hooks_notif[method] = handler
            return func

    @overload
    def hook_request(self, method: str) -> Callable[[TV], TV]:
        ...

    @overload
    def hook_request(self, method: str, func: TV) -> TV:
        ...

    def hook_request(self, method: str, func=None):
        """Signal to the Remote that `func` is waiting for Requests of the
            provided `method` value.
        """
        if func is None:
            # Function NOT provided. Return a Decorator.
            return partial(self.hook_request, method)
        else:
            # Function provided. Hook it directly.
            params = len(signature(func).parameters)

            @wraps(func)
            async def handler(data: dict, conn: Remote):
                try:
                    if params == 1:
                        res = await func(data.get("params", None))
                    else:
                        res = await func(data.get("params", None), conn)
                except Exception as e:
                    await conn.respond(
                        data.get("id", "0"),
                        data.get("method", "NONE"),
                        err={
                            "code": type(e).__name__,
                            "message": str(e),
                            "data": e.args,
                        },
                    )
                else:
                    await conn.respond(
                        data.get("id", "0"), data.get("method", "NONE"), res=res
                    )

            self.hooks_request[method] = handler
            return func

    def hook_connect(self, func):
        """Add a Function to a List of Callables that will be called on every
            new Connection.
        """
        self.hooks_connection.append(func)
        return func

    async def broadcast(
        self,
        meth: str,
        params: Union[dict, list] = None,
        default=None,
        *,
        callback=None,
        **kw,
    ) -> Dict[Remote, Task]:
        if not self.remotes:
            return {}

        reqs = {
            r: self.eventloop.create_task(
                r.request_wait(meth, params, default, callback=callback, **kw)
            )
            for r in self.remotes
        }
        return reqs

    async def bcast_notif(
        self, meth: str, params: Union[dict, list] = None, **kw,
    ) -> Dict[Remote, Task]:
        if not self.remotes:
            return {}

        reqs = {
            r: self.eventloop.create_task(r.notif(meth, params, **kw))
            for r in self.remotes
        }
        return reqs

    async def broadcast_wait(
        self,
        meth: str,
        params: Union[dict, list] = None,
        default=None,
        *,
        callback=None,
        **kw,
    ):
        reqs = await self.broadcast(meth, params, default, callback=callback, **kw)

        wins = await gather(*reqs.values(), return_exceptions=True)
        total = len(reqs)
        wincount = total - wins.count(None)

        echo("win", f"Messages successfully Broadcast: {wincount}/{total}")
        return list(zip(reqs.keys(), wins))

    def drop(self, remote: Remote):
        if remote in self.remotes:
            self.total_sent.update(remote.total_sent)
            self.total_recv.update(remote.total_recv)
            self.remotes.remove(remote)

    async def encrypt_remote(self, remote: Remote):
        echo("info", f"Starting Secure Connection with {remote}...")
        try:
            if await wait_for(remote.enable_rsa(), 10):
                echo("win", f"Secure Connection established with {remote}.")
            else:
                warn(f"Failed to establish Secure Connection with {remote!r}.")
        except TimeoutError:
            warn(f"Encryption Request to {remote!r} timed out.")

    async def terminate(self, reason: str = "Server Closing"):
        for remote in list(self.remotes):
            await remote.terminate(reason)
            self.drop(remote)
        self.remotes.clear()

        for task in self.listeners:
            task.cancel()

        if self.server.is_serving():
            self.server.close()
            await self.server.wait_closed()

        self.server = None
        echo("dcon", "Server closed.")

    async def open_connection(self, str_in: StreamReader, str_out: StreamWriter):
        """Callback executed by AsyncIO when a Client contacts the Server."""
        echo(
            "con",
            "Incoming Connection from Client at `{}`.".format(
                str_out.get_extra_info("peername", ("Unknown Address", 0))[0]
            ),
        )
        remote = Remote(self.eventloop, str_in, str_out, rtype="Client")
        self.total_clients += 1

        # Update the Client Hooks with our own.
        remote.hooks_notif_inher = self.hooks_notif
        remote.hooks_request_inher = self.hooks_request
        remote.startup = self.startup

        self.remotes.add(remote)
        echo("diff", f"Client at {remote.host} has been assigned UUID {remote.id}.")

        listening = self.eventloop.create_task(remote.loop(self.helpers))
        self.listeners.add(listening)

        def cb(*_):
            if listening in self.listeners:
                self.listeners.remove(listening)

        listening.add_done_callback(cb)

        # # Encrypt the Remote Connection.
        # rsa = self.eventloop.create_task(self.encrypt_remote(remote))

        for hook in self.hooks_connection:
            try:
                await hook(remote)
            except Exception as e:
                err(f"Failed to run {hook.__name__!r} on {remote!r}:", e)

        try:
            # Run the Remote Loop Coroutine. While this runs, messages received
            #   from the Remote Client are added to the Queue of the Remote
            #   object. This Coroutine also dispatches other Tasks to handle the
            #   received messages.
            await listening

        except CancelledError:
            pass

        finally:
            try:
                # Try not to drop the remote before the RSA Handshake is done.
                # await wait_for(rsa, 3)
                pass
            except (RuntimeError, TimeoutError):
                pass
            self.drop(remote)

    async def run(self, loop=None):
        """Server Coroutine. Does not setup or wrap the Server. Intended for use
            in instances where other things must be done, and the Server needs
            to be run properly asynchronously.
        """
        self.eventloop = loop or get_event_loop()

        echo("info", f"Running Server on {self.addr}:{self.port}")
        self.server = await start_server(
            self.open_connection, self.addr, self.port, loop=self.eventloop
        )
        echo("win", "Ready to begin accepting Requests.")
        # noinspection PyUnresolvedReferences
        tsk = self.eventloop.create_task(self.server.serve_forever())
        tsk.add_done_callback(self.report)
        return tsk

    def report(self, *_):
        try:
            echo(
                "info",
                f"Served {self.total_clients} Clients in"
                f" {str(dt.utcnow() - self.startup)[:-7]}.",
            )
            echo("info", "Sent:")
            echo(
                "tab",
                [
                    f"> {v} {k.capitalize()}{'' if v == 1 else 's'}"
                    for k, v in self.total_sent.items()
                ],
            )
            echo("info", "Received:")
            echo(
                "tab",
                [
                    f"> {v} {k.capitalize()}{'' if v == 1 else 's'}"
                    for k, v in self.total_recv.items()
                ],
            )
        except:
            pass

    def start(self, *a, **kw):
        """Run alone and do nothing else. For very simple implementations that
            do not need to do anything else at the same time.
        """
        self.setup(*a, **kw)

        try:
            run(self.run())
        except KeyboardInterrupt:
            err("INTERRUPTED. Server closing...")
            run(self.terminate("Server Interrupted"))
        except Exception as e:
            err("Server closing due to unexpected", e)
            run(self.terminate("Fatal Server Error"))
        else:
            echo("dcon", "Server closing...")
            run(self.terminate())
        # finally:
        #     try:
        #         self.report()
        #     except Exception:
        #         return
