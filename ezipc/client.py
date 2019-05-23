import asyncio
from datetime import datetime as dt

from .common import Remote


class Client:
    def __init__(self, addr: str = "127.0.0.1", port: int = 9002):
        self.addr = addr
        self.port = port
        self.remote = None
        self.listening = None
        self.startup = dt.utcnow()

    @property
    def alive(self):
        return bool(self.remote and not self.remote.outstr.is_closing())

    async def _setup(self):
        async def cb_recv(data, conn):
            print(
                "    Received '{}' from Remote {}.".format(
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
            print("(i) Server Uptime: {}".format(dt.utcnow() - self.startup))

        await self.remote.request("TIME", callback=cb_time)

    async def connect(self):
        streams = await asyncio.open_connection(self.addr, self.port)
        self.remote = Remote(*streams)
        print(
            "Connected to Host. Server has been given the alias '{}'.".format(
                self.remote.id
            )
        )
        await self._setup()

    def run_through(self, *coros):
        """Construct a Coroutine that will sequentially run an arbitrary number
            of other Coroutines, passed to this method. Then, run the newly
            constructed Coroutine, while listening.
        """

        async def run():
            await self.connect()
            self.listening = asyncio.create_task(self.remote.loop())

            for coro in coros:
                await coro(self)

            await asyncio.sleep(60)
            self.listening.cancel()
            self.listening = None

        try:
            asyncio.run(run())
        except ConnectionRefusedError:
            print("Connection Refused.")
        except ConnectionError as e:
            print("{}: {}".format(type(e).__name__, e))
        except KeyboardInterrupt:
            print("INTERRUPTED. Client closing...")
        except Exception as e:
            print("Client closing due to unexpected {}: {}".format(type(e).__name__, e))
        else:
            print("Done.")
        finally:
            try:
                asyncio.run(self.remote.close())
            except Exception:
                return
