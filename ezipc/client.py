import asyncio
from datetime import datetime as dt

from .common import Remote
from .output import echo, err, P, warn


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
        self.addr = addr
        self.port = port

        self.eventloop = None
        self.remote = None
        self.listening = None

        self.startup = dt.utcnow()

    @property
    def alive(self):
        return bool(self.remote and not self.remote.outstr.is_closing())

    async def _add_hooks(self):
        response = await self.remote.request("TIME")

        async def cb_census(data, conn):
            echo(
                "info",
                "Currently {} Client(s) connected to {}.".format(
                    data.get("params", {}).get("client_count", "(?)"), conn
                ),
            )
            await conn.respond(data["id"], data["method"], res=[True])

        self.remote.hook_request("CENSUS", cb_census)

        # await self.remote.request("TIME", callback=cb_time)
        await response

        if response.cancelled() or response.exception():
            warn("Failed to get Server Uptime.")
        else:
            ts = response.result().get("startup", 0)
            if ts:
                self.startup = dt.fromtimestamp(ts)
                P.startup = self.startup
                echo("info", "Server Uptime: {}".format(dt.utcnow() - self.startup))

    async def connect(self, loop):
        streams = await asyncio.open_connection(self.addr, self.port, loop=loop)
        self.remote = Remote(loop, *streams)
        echo(
            "con",
            "Connected to Host. Server has been given the alias '{}'.".format(
                self.remote.id
            ),
        )
        self.listening = loop.create_task(self.remote.loop())
        await self._add_hooks()

    async def disconnect(self):
        if self.listening:
            if not self.listening.done():
                self.listening.cancel()
            self.listening = None

        if self.alive:
            try:
                await self.remote.close()
            except Exception:
                pass
            finally:
                self.remote = None

    async def terminate(self, death_rattle: str = None):
        try:
            await self.remote.terminate(death_rattle)
            echo("dcon", "Connection terminated.")
        except:
            err("Skipping niceties.")

    async def run_through(self, *coros, loop=None):
        """Construct a Coroutine that will sequentially run an arbitrary number
            of other Coroutines, passed to this method. Then, run the newly
            constructed Coroutine, while listening.
        """
        loop = loop or asyncio.get_running_loop()

        async def run():
            for coro in coros:
                await coro(self)

        try:
            await self.connect(loop)
            await run()

        except ConnectionRefusedError:
            err("Connection Refused.")
        except ConnectionError as e:
            err("Connection Lost:", e)

        except asyncio.CancelledError:
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
