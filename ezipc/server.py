from asyncio import (
    AbstractEventLoop,
    AbstractServer,
    CancelledError,
    Future,
    gather,
    get_event_loop,
    run,
    start_server,
    StreamReader,
    StreamWriter,
    Task,
)
from collections import Counter, MutableSet
from datetime import datetime as dt
from socket import AF_INET, SOCK_DGRAM, socket
from typing import Callable, Dict, Optional, Union

from .remote import (
    can_encrypt,
    counter,
    notif_handler,
    Remote,
    RemoteError,
    request_handler,
    rpc_response,
)
from .util import callback_response, echo, err, hl_method, P, T, warn


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
        "hooks_disconnect",
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
        self.hooks_connection = []
        self.hooks_disconnect = []

    def setup(self, *_a, **_kw):
        """Execute all prerequisites to running, before running. Meant to be
            extended by Subclasses.
        """

        @self.hook_request("ETC.INIT")
        async def cb_time(_, remote: Remote):
            return {"startup": self.startup.timestamp(), "id": remote.id}

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

    def hook_connect(self, func):
        """Add a Function to a List of Callables that will be called on every
            new Connection.
        """
        self.hooks_connection.append(func)
        return func

    def hook_disconnect(self, func):
        """Add a Function to a List of Callables that will be called whenever a
            Remote is closed.
        """
        self.hooks_disconnect.append(func)
        return func

    async def bcast_notif(
        self, meth: str, params: Union[dict, list, tuple] = None, **kw,
    ) -> Dict[Remote, Task]:
        """Send a Notification to every connected Remote. Return a Dict which
            maps each Remote to its respective sending Task. These Tasks must
            then be awaited.
        """
        echo(
            "cast",
            f"Broadcasting {hl_method(meth)} Notif to {len(self.remotes)}"
            f" Remote{'' if len(self.remotes) == 1 else 's'}.",
        )
        if not self.remotes:
            return {}

        return {
            remote: self.eventloop.create_task(
                remote.notif(meth, params, quiet=True, **kw)
            )
            for remote in self.remotes
        }

    async def bcast_request(
        self, meth: str, params: Union[dict, list, tuple] = None, **kw,
    ) -> Dict[Remote, Future]:
        """Send a Request to every connected Remote. Return a Dict which maps
            each Remote to the Future (or Exception) returned from the
            respective message sent.

        Unlike ``bcast_notif()``, this Method will await sending the Message.
            The objects returned are the Futures which will receive the
            Responses from the Remote.
        """
        echo(
            "cast",
            f"Broadcasting {hl_method(meth)} Request to {len(self.remotes)}"
            f" Remote{'' if len(self.remotes) == 1 else 's'}.",
        )
        if not self.remotes:
            return {}

        tasks: Dict[Remote, Task] = {
            remote: self.eventloop.create_task(
                remote.request(meth, params, quiet=True, **kw)
            )
            for remote in self.remotes
        }
        await gather(*tasks.values(), return_exceptions=True)
        return {
            remote: (task.exception() or task.result())
            for remote, task in tasks.items()
        }

    def drop(self, remote: Remote):
        if remote in self.remotes:
            self.remotes.remove(remote)
            self.total_sent.update(remote.total_sent)
            self.total_recv.update(remote.total_recv)

    async def terminate(self, reason: str = "Server Closing"):
        for remote in list(self.remotes):
            try:
                await remote.terminate(reason)
            except Exception as e:
                warn(f"Unknown Error from {remote!r}:", e)
            finally:
                self.drop(remote)

        self.remotes.clear()

        if self.server.is_serving():
            self.server.close()
            await self.server.wait_closed()

        self.server = None
        echo("dcon", "Server closed.")

    async def open_connection(self, str_in: StreamReader, str_out: StreamWriter):
        """Callback executed by AsyncIO when a Client contacts the Server."""
        remote = Remote(self.eventloop, str_in, str_out, rtype="Client")
        echo(
            "con", f"Incoming Connection from Client at {T.bold_green(remote.host)}.",
        )
        self.total_clients += 1

        # Update the Client Hooks with our own.
        remote.hooks_notif_inher = self.hooks_notif
        remote.hooks_request_inher = self.hooks_request
        remote.startup = self.startup

        self.remotes.add(remote)
        echo("diff", f"Client at {remote.host} has been assigned UUID {remote.id}.")

        listening = self.eventloop.create_task(remote.loop(self.helpers))
        self.listeners.add(listening)

        for hook in self.hooks_connection:
            # Run all necessary Connection Hooks.
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

        except Exception as e:
            warn(f"Unknown Error from {remote!r}:", e)

        finally:
            if listening in self.listeners:
                self.listeners.remove(listening)
            try:
                for hook in self.hooks_disconnect:
                    try:
                        await hook(remote)
                    except Exception as e:
                        err(f"Failed to run {hook.__name__!r} on {remote!r}:", e)

            except Exception as e:
                warn(f"Unknown Error from {remote!r}:", e)

            finally:
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
