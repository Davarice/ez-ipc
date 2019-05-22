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
        self.loop = None
        self.remotes = set()
        self.running = None
        self.startup = None

    def attach(self, loop=None):
        """Attach to an Event Loop."""
        self.loop = loop or asyncio.get_event_loop()
        self.startup = asyncio.start_server(
            self.accept_connection, self.addr, self.port, loop=self.loop
        )

    def _setup(self, *a, **kw):
        """Execute all prerequisites to running, before running. Meant to be
            overwritten by Subclasses.
        """
        pass

    def run(self, *a, **kw):
        """Execute final Setup, and then run the Server."""
        if not self.loop:
            return

        self._setup(*a, **kw)
        self.running = self.loop.run_until_complete(self.startup)

        try:
            print("Running Server...")
            self.loop.run_forever()
        except KeyboardInterrupt:
            print("INTERRUPTED. Server closing...")
        else:
            print("Server closing...")
        finally:
            self.kill()

    def kill(self):
        if self.running:
            self.running.close()
            self.loop.run_until_complete(self.running.wait_closed())
            self.running = None
        self.loop.close()
        print("Server closed.")

    async def accept_connection(
        self, str_in: asyncio.StreamReader, str_out: asyncio.StreamWriter
    ):
        """Callback executed by AsyncIO when a Client contacts the Server."""
        print("Incoming Connection from Client at `{}`.".format(str_out.get_extra_info("peername", "Unknown Address")))
        con = Tunnel(str_in, str_out)
        self.remotes.add(con)
        await asyncio.create_task(con.loop())


z = Server()
z.attach()
z.run()
