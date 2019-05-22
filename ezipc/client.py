import asyncio

from .common import Tunnel


class Client:
    def __init__(self, addr: str = "127.0.0.1", port: int = 9002):
        self.addr = addr
        self.port = port
        self.con = None
        self.listening = None

    def _setup(self, *a, **kw):
        """Execute all prerequisites to running, before running. Meant to be
            overwritten by Subclasses.
        """
        pass

    async def connect(self):
        self._setup()
        streams = await asyncio.open_connection(self.addr, self.port)
        self.con = Tunnel(*streams)
        print("Connected to {}.".format(self.con.host))

    def run_through(self, *coros):
        async def run():
            await self.connect()
            listening = asyncio.create_task(self.con.loop())

            for coro in coros:
                await coro(self)

            await asyncio.sleep(1)
            listening.cancel()

        try:
            asyncio.run(run())
        except ConnectionError as e:
            print("{}: {}".format(type(e).__name__, e))
        except KeyboardInterrupt:
            print("INTERRUPTED. Client closing...")
        else:
            print("Done.")
        finally:
            self.con.kill()
