import asyncio

from .etc import nextline, ConnectionKill


class Remote:
    def __init__(self, str_in, str_out, group=None):
        self.str_in: asyncio.StreamReader = str_in
        self.str_out: asyncio.StreamWriter = str_out

        self.addr, self.port = self.str_out.get_extra_info("peername", ("0.0.0.0", 0))
        self.coro = self.listen()
        self.group: set = group
        if self.group is not None:
            self.group.add(self)

    @property
    def host(self):
        return ":".join((self.addr, str(self.port)))

    def listen(self):
        return asyncio.create_task(self._loop())

    async def handle_line(self, line: bytes):
        if line == b"END\n":
            # Receiving END signal. Return ACK and raise KILL signal.
            await self.send(b"END_ACK\n")
            raise ConnectionKill("terminated by remote request")
        elif line == b"END_ACK\n":
            # Receiving END_ACK signal. Its a good bet that the Remote closed.
            raise ConnectionKill("terminated by local request")
        else:
            line_s = line.decode("utf-8")

            print("Received data from {} - {}".format(self.host, repr(line_s)))
            await self.send(b"ACK %d - %s\n" % (len(line), line))

    async def _loop(self):
        try:
            while True:
                line: bytes = await nextline(self.str_in)
                await self.handle_line(line)

        except EOFError:
            print("Connection with {} hit EOF.".format(self.host))
        except ConnectionKill as e:
            print("Connection with {} {}.".format(self.host, e))
        finally:
            self.str_out.close()
            if self.group is not None and self in self.group:
                self.group.remove(self)

    async def send(self, data: bytes):
        self.str_out.write(data)
        await self.str_out.drain()


class Server:
    def __init__(self, addr: str = "127.0.0.1", port: int = 1729):
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
        """Callback executed by ASyncIO when a Client contacts the Server."""
        print("Incoming Connection from Client at `{}`.".format(str_out.get_extra_info("peername", "Unknown Address")))
        self.remotes.add(Remote(str_in, str_out, self.remotes))
        # line: bytes = await str_in.readline()
        # print("Received {} bytes from Client.".format(len(line.decode("utf-8"))))
        # str_out.write(b"ACK %d\n" % len(line))
        # await str_out.drain()


z = Server()
z.attach()
z.run()
