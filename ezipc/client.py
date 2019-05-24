import asyncio
from datetime import datetime as dt

from .common import Remote
from .output import echo, err, P


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
        self.remote = None
        self.listening = None
        self.startup = dt.utcnow()

    @property
    def alive(self):
        return bool(self.remote and not self.remote.outstr.is_closing())

    async def _add_hooks(self):
        async def cb_recv(data, conn):
            echo("",
                "Received '{}' from Remote {}.".format(
                    data.get("params", data["method"]), conn.id
                )
            )
            await conn.respond(data["id"], res=[True])

        self.remote.hook_request("CENSUS", cb_recv)

        async def cb_time(data, conn):
            ts = data.get("result", {}).get("startup", 0)
            if ts:
                self.startup = dt.fromtimestamp(ts)
                conn.startup = self.startup
                P.startup = self.startup
            echo("info", "Server Uptime: {}".format(dt.utcnow() - self.startup))

        await self.remote.request("TIME", callback=cb_time)

    async def connect(self, loop):
        streams = await asyncio.open_connection(self.addr, self.port)
        self.remote = Remote(*streams)
        echo("con",
            "Connected to Host. Server has been given the alias '{}'.".format(
                self.remote.id
            )
        )
        self.listening = loop.create_task(self.remote.loop())
        await self._add_hooks()

    async def disconnect(self):
        if self.listening:
            self.listening.cancel()
            self.listening = None

        if self.alive:
            try:
                await self.remote.close()
            except Exception:
                return

    async def run_through(self, *coros, loop=None):
        """Construct a Coroutine that will sequentially run an arbitrary number
            of other Coroutines, passed to this method. Then, run the newly
            constructed Coroutine, while listening.
        """
        loop = loop or asyncio.get_running_loop()

        async def run():
            for coro in coros:
                await coro(self)
            await asyncio.sleep(60)

        try:
            await self.connect(loop)
            await run()
        except ConnectionRefusedError:
            err("Connection Refused.")
        except ConnectionError as e:
            err("Connection Lost:", e)

        except asyncio.CancelledError:
            err("CANCELLED. Client closing...")
            try:
                await self.remote.terminate("Coroutine Cancelled")
                echo("info", "Connection ended.")
            except:
                err("Closing immediately.")

        except KeyboardInterrupt:
            err("INTERRUPTED. Client closing...")
            try:
                await self.remote.terminate("KeyboardInterrupt")
                echo("info", "Connection ended.")
            except:
                err("Closing immediately.")

        except Exception as e:
            err("Client closing due to unexpected", e)
        else:
            echo("", "Done.")
        finally:
            await self.disconnect()
