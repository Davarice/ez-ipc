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

        self.clients = set()
        self.server = None

    def _setup(self, *a, **kw):
        """Execute all prerequisites to running, before running. Meant to be
            overwritten by Subclasses.
        """
        pass

    async def kill(self):
        for client in self.clients:
            client.kill()
        if self.server.is_serving():
            self.server.close()
            await self.server.wait_closed()
        print("Server closed.")

    async def open_connection(
        self, str_in: asyncio.StreamReader, str_out: asyncio.StreamWriter
    ):
        """Callback executed by AsyncIO when a Client contacts the Server."""
        print(
            "Incoming Connection from Client at `{}`.".format(
                str_out.get_extra_info("peername", "Unknown Address")
            )
        )
        client = Tunnel(str_in, str_out)
        self.clients.add(client)
        await client.loop()

    async def run(self, loop=None):
        """Server Coroutine. Does not setup or wrap the Server. Intended for use
            in instances where other things must be done, and the Server needs
            to be run properly asynchronously.
        """
        print("Running Server on {}:{}".format(self.addr, self.port))
        self.server = await asyncio.start_server(
            self.open_connection,
            self.addr,
            self.port,
            loop=loop or asyncio.get_event_loop(),
        )
        await self.server.serve_forever()

    def start(self, *a, **kw):
        """Run alone and do nothing else. For very simple implementations that
            do not need to do anything else at the same time.
        """
        self._setup(*a, **kw)

        try:
            asyncio.run(self.run())
        except KeyboardInterrupt:
            print("INTERRUPTED. Server closing...")
        else:
            print("Server closing...")
        finally:
            asyncio.run(self.kill())
