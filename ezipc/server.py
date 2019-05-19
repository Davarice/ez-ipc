import asyncio


class Server:
    def __init__(self, addr: str = "127.0.0.1", port: int = 1729):
        self.addr = addr
        self.port = port
        self.loop = None
        self.running = None
        self.startup = None

    def attach(self, loop=None):
        """Attach to an Event Loop."""
        self.loop = loop or asyncio.get_event_loop()
        self.startup = asyncio.start_server(
            self.accept_connection, self.addr, self.port, loop=self.loop
        )

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

    def _setup(self, *a, **kw):
        """Execute all prerequisites to running, before running. Meant to be
            overwritten by Subclasses.
        """
        pass

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
        """Callback executed by ASyncIO when a Client contacts the Server."""
        print("Incoming Connection from Client at `{}`.".format(str_out.get_extra_info("peername", "Unknown Address")))
        line: bytes = await str_in.readline()
        print("Received {} bytes from Client.".format(len(line.decode("utf-8"))))
        str_out.write(b"ACK %d\n" % len(line))


z = Server()
z.attach()
z.run()
