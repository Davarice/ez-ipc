import asyncio


class Client:
    def __init__(self, addr: str = "127.0.0.1", port: int = 1729):
        self.addr = addr
        self.port = port
        self.loop = asyncio.get_event_loop()
        self.str_in, self.str_out = None, None

    def setup(self, *a, **kw):
        """Execute all prerequisites to running, before running. Meant to be
            overwritten by Subclasses.
        """
        pass

    def run(self, *a, **kw):
        self.setup(*a, **kw)

        try:
            print("Running Client...")
            self.loop.run_until_complete(self.execute())
        except KeyboardInterrupt:
            print("INTERRUPTED. Client closing...")
        else:
            print("Client closing...")
        finally:
            self.loop.close()
            print("Client closed.")

    async def send(self, data: bytes):
        self.str_out.write(data if data[-1] == 10 else data + b"\n")
        await self.str_out.drain()

    async def execute(self):
        """Core execution method, should return usable Stream objects.
            Example/test method, meant to be overwritten by Subclasses.
        """
        print("Sending Requests.")
        self.str_in, self.str_out = await asyncio.open_connection(
            self.addr, self.port, loop=self.loop
        )

        for i in ["aaaa", "zxcv", "END"]:
            await asyncio.sleep(3)
            print("Sending...")
            await self.send((str(i)).encode("utf-8"))
            print("Sent.")
            print("Reading...")
            line: bytes = await self.str_in.readline()
            print("Received Server response: {}".format(repr(line)))


Client().run()
