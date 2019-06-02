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

from .remote import can_encrypt, handled, Remote, RemoteError, request_handler
from .util import callback_response, echo, err, P, warn


__all__ = [
    "callback_response",
    "can_encrypt",
    "Client",
    "echo",
    "err",
    "handled",
    "P",
    "Remote",
    "RemoteError",
    "request_handler",
    "warn",
]


class Client:
    """The Client is the component of the Client/Server Model that connects to
        a Server and sends it input. In certain cases the Client will also wait
        for returned data from the Server, such as Responses to Requests sent by
        the Client. Rarely, the Client may also be designed to accept data which
        was not expressly requested, such as a live chat program.

    As the more active component, the Client will often spend most of its time
        sending Messages, or waiting for Responses.
    """

    def __init__(self, addr: str = "127.0.0.1", port: int = 9002):
        self.addr: str = addr
        self.port: int = port

        self.eventloop: AbstractEventLoop = None
        self.remote: Remote = None
        self.listening: Task = None

        self.startup: dt = dt.utcnow()

    @property
    def alive(self):
        return bool(self.remote and not self.remote.outstr.is_closing())

    async def _add_hooks(self):
        response = await self.remote.request_wait("TIME")

        if response:
            ts = response.get("startup", 0)
            if ts:
                self.startup = dt.fromtimestamp(ts)
                P.startup = self.startup
                echo("info", "Server Uptime: {}".format(dt.utcnow() - self.startup))
        else:
            warn("Failed to get Server Uptime.")

    async def connect(self, loop, helpers=5, timeout=10) -> bool:
        try:
            streams = await wait_for(
                open_connection(self.addr, self.port, loop=loop), timeout
            )
        except TimeoutError:
            err("Connection timed out after {}s.".format(timeout))
            return False
        except ConnectionRefusedError:
            err("Connection Refused.")
            return False
        except ConnectionError as e:
            err("Connection Lost:", e)
            return False

        self.remote = Remote(loop, *streams)
        echo(
            "con",
            "Connected to Host. Server has been given the alias '{}'.".format(
                self.remote.id
            ),
        )
        self.listening = loop.create_task(self.remote.loop(helpers))
        await self._add_hooks()
        return True

    async def disconnect(self):
        if self.listening:
            if not self.listening.done():
                self.listening.cancel()
            self.listening: Task = None

        if self.alive:
            try:
                await self.remote.close()
            except Exception:
                pass
            finally:
                self.remote = None

    async def terminate(self, reason: str = None):
        try:
            await self.remote.terminate(reason)
            echo("dcon", "Connection terminated.")
        except:
            err("Skipping niceties.")

    async def run_through(self, *coros, loop: AbstractEventLoop = None):
        """Construct a Coroutine that will sequentially run an arbitrary number
            of other Coroutines, passed to this method. Then, run the newly
            constructed Coroutine, while listening.
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
                echo("info", "Sent:")
                echo(
                    "tab",
                    [
                        "> {} {}s".format(v, k.capitalize())
                        for k, v in self.remote.total_sent.items()
                    ],
                )
                echo("info", "Received:")
                echo(
                    "tab",
                    [
                        "> {} {}s".format(v, k.capitalize())
                        for k, v in self.remote.total_recv.items()
                    ],
                )
                await self.disconnect()
