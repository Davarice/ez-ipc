import asyncio

from .common import Tunnel


class Client:
    def __init__(self, addr: str = "127.0.0.1", port: int = 9002):
        self.addr = addr
        self.port = port
        self.con = None

    def _setup(self, *a, **kw):
        """Execute all prerequisites to running, before running. Meant to be
            overwritten by Subclasses.
        """
        pass

    async def connect(self):
        streams = await asyncio.open_connection(self.addr, self.port)
        self.con = Tunnel(*streams)

    async def execute(self):
        """Core execution method, should return usable Stream objects.
            Example/test method, meant to be overwritten by Subclasses.
        """
        print("Connecting...")
        await self.connect()

        print("Sending Requests in three seconds.")
        for i in ["aaaa", "zxcv", "END"]:
            await asyncio.sleep(3)
            print("Sending...")
            uuid, ts = await self.con.request("ping", [i])
            self.con.hook_response(uuid.hex, self.receive)
            print("Sent. Waiting for Response...")
            await self.con.get_data()

    async def receive(self, data):
        print("Received Server response: {}".format(repr(data)))

    async def run(self, *a, **kw):
        self._setup(*a, **kw)

        try:
            print("Running Client...")
            await self.execute()
        except ConnectionError as e:
            print("{}: {}".format(type(e).__name__, e))
        except KeyboardInterrupt:
            print("INTERRUPTED. Client closing...")
        else:
            print("Client closing...")
        finally:
            print("Client closed.")


asyncio.run(Client().run())
