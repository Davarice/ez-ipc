import asyncio

from .common import Tunnel


class Server:
    def __init__(self, addr: str = "", port: int = 9002, autopublish=False):
        if autopublish:
            # TODO: Find the network address of this machine.
            pass
        elif not addr:
            addr = "127.0.0.1"

        self.addr = addr
        self.port = port

        self.remotes = set()
        self.server = None

    def _setup(self, *a, **kw):
        """Execute all prerequisites to running, before running. Meant to be
            overwritten by Subclasses.
        """
        pass

    async def open_connection(
        self, str_in: asyncio.StreamReader, str_out: asyncio.StreamWriter
    ):
        """Callback executed by AsyncIO when a Client contacts the Server."""
        print(
            "Incoming Connection from Client at `{}`.".format(
                str_out.get_extra_info("peername", "Unknown Address")
            )
        )
        con = Tunnel(str_in, str_out)
        self.remotes.add(con)
        await asyncio.create_task(con.loop())

    async def run(self, *a, **kw):
        """Execute final Setup, and then run the Server."""
        self._setup(*a, **kw)

        try:
            print("Running Server on {}:{}".format(self.addr, self.port))
            self.server = await asyncio.start_server(
                self.open_connection, self.addr, self.port
            )
            await self.server.serve_forever()
        except KeyboardInterrupt:
            print("INTERRUPTED. Server closing...")
        else:
            print("Server closing...")
        finally:
            await self.kill()

    async def kill(self):
        if self.server.is_serving():
            self.server.close()
            await self.server.wait_closed()
        print("Server closed.")


asyncio.run(Server().run())
