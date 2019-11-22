from asyncio import (
    AbstractEventLoop,
    CancelledError,
    get_running_loop,
    open_connection,
    Task,
    TimeoutError,
    wait_for,
)
from datetime import datetime as dt
from functools import partial, wraps
from typing import Callable, Optional, overload, Union

from .remote import (
    can_encrypt,
    mkid,
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
    "Client",
    "echo",
    "err",
    "rpc_response",
    "P",
    "Remote",
    "RemoteError",
    "request_handler",
    "warn",
)


class Client:
    """The Client is the component of the Client/Server Model that connects to
    a Server and sends it input. In certain cases the Client will also wait for
    returned data from the Server, such as Responses to Requests sent by the
    Client. Rarely, the Client may also be designed to accept data which was not
    expressly requested, such as a live chat program.

    As the more active component, the Client will often spend most of its time
    sending Messages, or waiting for Responses.

    :param str addr: IPv4 Address of the Server this Client will connect to. If
        this is not supplied, ``127.0.0.1`` will be used.
    :param int port: IP Port of the Server to use.
    """

    __slots__ = (
        "addr",
        "port",
        "eventloop",
        "remote",
        "listening",
        "startup",
        "hooks_notif",
        "hooks_request",
    )

    def __init__(self, addr: str = "127.0.0.1", port: int = 9002):
        self.addr: str = addr
        self.port: int = port

        self.eventloop: Optional[AbstractEventLoop] = None
        self.remote: Optional[Remote] = None
        self.listening: Optional[Task] = None

        self.startup: dt = dt.utcnow()

        self.hooks_notif = {}
        self.hooks_request = {}

    @property
    def alive(self) -> bool:
        """Determine whether the Remote is still connected."""
        return bool(self.remote and not self.remote.outstr.is_closing())

    async def setup(self):
        response = await self.remote.request_wait("TIME")

        if response:
            self.remote.id = response.get("id") or mkid(self.remote)
            ts = response.get("startup", 0)
            if ts:
                self.startup = dt.fromtimestamp(ts)
                P.startup = self.startup
                echo("info", f"Server Uptime: {dt.utcnow() - self.startup}")
        else:
            warn("Failed to get Server Uptime.")

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
            @wraps(func)
            async def handler(data: dict, conn: Remote):
                try:
                    res = await func(data.get("params", None))
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

    async def connect(
        self, loop: AbstractEventLoop, helpers: int = 5, timeout: Union[float, int] = 10
    ) -> bool:
        """Connect to a Server and create a Remote Object around its Streams.
        Then, establish Client Request and Notification Hooks with the Remote,
        and finally start a Task in the Event Loop to run the Remote.

        :param AbstractEventLoop loop: An AsyncIO Event Loop, or an external
            subclass thereof. The Loop on which to run the Remote.
        :param int helpers: The number of Helper Tasks to be used by the Remote.
            More Helpers can be useful when receiving prompts to perform very
            await-heavy procedures, such as multiple file transfers, but when
            not in use they mostly sap memory.
        :param Union[float, int] timeout: The number of seconds to wait before
            giving up on trying to connect.

        :return: True if the Connection was successful, otherwise False.
        """
        try:
            streams = await wait_for(
                open_connection(self.addr, self.port, loop=loop), timeout
            )
        except TimeoutError:
            err(f"Connection timed out after {timeout}s.")
            return False
        except ConnectionRefusedError:
            err("Connection Refused.")
            return False
        except ConnectionError as e:
            err("Connection Lost:", e)
            return False

        try:
            self.remote = Remote(loop, *streams, rtype="Server", remote_id="000")
            self.remote.hooks_notif_inher = self.hooks_notif
            self.remote.hooks_request_inher = self.hooks_request
            self.listening = loop.create_task(self.remote.loop(helpers))
            self.listening.add_done_callback(self.report)
        except:
            return False
        else:
            try:
                await self.setup()
            except:
                warn(
                    f"Connection to {self.remote.id!r} successful, but Client"
                    f" Setup failed."
                )
                return False
            else:
                echo(
                    "con",
                    f"Connected to Host. Server has been given the alias"
                    f" {self.remote.id!r}.",
                )

            return True

    async def disconnect(self):
        """Forcibly break the Remote Connection. The Listening Task will be
        cancelled and ``Remote.close()`` will be called.
        """
        if self.listening:
            if not self.listening.done():
                self.listening.cancel()
            self.listening: Optional[Task] = None

        if self.alive:
            try:
                await self.remote.close()
            except Exception:
                pass
            finally:
                self.remote = None

    async def terminate(self, reason: str = None):
        """Politely close the Remote Connection. Calls ``Remote.terminate()``
        and passes the Reason, if any, through.

        :param str reason: An optional Message to be sent to the Remote, giving
            the reason for the disconnect; For example, "Program Completed" or
            "User Timed Out".
        """
        try:
            await self.remote.terminate(reason)
            echo("dcon", "Connection terminated.")
        except:
            err("Skipping niceties.")

    def report(self, *_):
        try:
            echo("info", "Sent:")
            echo(
                "tab",
                [
                    f"> {v} {k.capitalize()}{'' if v == 1 else 's'}"
                    for k, v in self.remote.total_sent.items()
                ],
            )
            echo("info", "Received:")
            echo(
                "tab",
                [
                    f"> {v} {k.capitalize()}{'' if v == 1 else 's'}"
                    for k, v in self.remote.total_recv.items()
                ],
            )
        except:
            pass

    async def run_through(self, *coros: Callable, loop: AbstractEventLoop = None):
        """Construct a Coroutine that will sequentially run an arbitrary number
        of other Coroutines passed to this method. Then, connect to the Remote
        and run the newly constructed Coroutine.

        Depending on your specific Project structure, this may be considered the
        "entry point" of the Client.

        :param Callable coros: Any number of Coroutines. They will be run, in
            order, with the Client Instance passed in as the only Parameter. The
            Client will then close.
        :param AbstractEventLoop loop: An AsyncIO Event Loop, or an external
            subclass thereof, such as a Qt Event Loop. This is the Event Loop
            on which the entire Client and its Remote will run.
        """
        loop: AbstractEventLoop = loop or get_running_loop()

        async def run():
            for coro in coros:
                await coro(self)

        try:
            if await self.connect(loop):
                await run()

        except CancelledError:
            err("CANCELLED. Client closing...")
            await self.terminate("Coroutine Cancelled")

        except KeyboardInterrupt:
            err("INTERRUPTED. Client closing...")
            await self.terminate("KeyboardInterrupt")

        except Exception as e:
            err("Client closing due to unexpected", e)
        else:
            echo("win", "Program complete. Closing...")
            await self.terminate("Program Completed")

        finally:
            if self.remote:
                self.report()
                await self.disconnect()
