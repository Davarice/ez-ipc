import asyncio

from .common import Tunnel


class Client:
    def __init__(self, addr: str = "127.0.0.1", port: int = 9002):
        self.addr = addr
        self.port = port
        self.con = None
        self.listening = None

    @property
    def alive(self):
        return bool(self.con and not self.con.outstr.is_closing())

    def _setup(self, *a, **kw):
        """Execute all prerequisites to running, before running. Meant to be
            overwritten by Subclasses.
        """
        pass

    async def connect(self):
        self._setup()
        streams = await asyncio.open_connection(self.addr, self.port)
        self.con = Tunnel(*streams)
        print(
            "Connected to Host. Server has been given the alias '{}'.".format(
                self.con.id
            )
        )

    def run_through(self, *coros):
        """Construct a Coroutine that will sequentially run an arbitrary number
            of other Coroutines, passed to this method. Then, run the newly
            constructed Coroutine, while listening.
        """

        async def recv(data, conn):
            # print("Receiving")
            print(
                "    Received '{}' from Remote {}.".format(
                    data.get("params", data["method"]), conn.id
                )
            )
            await conn.respond(data["id"], res=[True])

        async def run():
            await self.connect()
            self.con.hook_request("CENSUS", recv)
            self.listening = asyncio.create_task(self.con.loop())

            for coro in coros:
                await coro(self)

            await asyncio.sleep(60)
            self.listening.cancel()
            self.listening = None

        try:
            asyncio.run(run())
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
                asyncio.run(self.con.close())
            except Exception:
                return
