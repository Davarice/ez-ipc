import asyncio


class Server:
    def __init__(self, addr: str = "127.0.0.1", port: int = 1729):
        self.loop = asyncio.get_event_loop()
        self.startup = asyncio.start_server(
            self.receive_request, addr, port, loop=self.loop
        )
        self.running = None

    def setup(self, *a, **kw):
        """Execute all prerequisites to running, before running. Meant to be
            overwritten by Subclasses.
        """
        pass

    def run(self, *a, **kw):
        self.setup(*a, **kw)
        self.running = self.loop.run_until_complete(self.startup)

        try:
            print("Running Server...")
            self.loop.run_forever()
        except KeyboardInterrupt:
            print("INTERRUPTED. Server closing...")
        else:
            print("Server closing...")
        finally:
            self.running.close()
            self.loop.run_until_complete(self.running.wait_closed())
            self.loop.close()
            print("Server closed.")

    async def receive_request(
        self, str_in: asyncio.StreamReader, str_out: asyncio.StreamWriter
    ):
        """Callback executed by ASyncIO when a Client contacts the Server.
            Example/test method, meant to be overwritten by Subclasses.
        """
        print("Receiving Request...")
        line: bytes = await str_in.readline()
        print("Received {} bytes from Client.".format(len(line.decode("utf-8"))))
        str_out.write(b"ACK %d\n" % len(line))


Server().run()
