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

        self.hooks_notif = {}
        self.hooks_request = {}

    def _setup(self, *a, **kw):
        """Execute all prerequisites to running, before running. Meant to be
            overwritten by Subclasses.
        """
        pass

    def hook_notif(self, method: str, func):
        """Signal to the Tunnel that `func` is waiting for Notifications of the
            provided `method` value.
        """
        self.hooks_notif[method] = func

    def hook_request(self, method: str, func):
        """Signal to the Tunnel that `func` is waiting for Requests of the
            provided `method` value.
        """
        self.hooks_request[method] = func

    async def kill(self):
        for client in self.clients:
            await client.kill()
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
                str_out.get_extra_info("peername", ("Unknown Address", 0))[0]
            )
        )
        client = Tunnel(str_in, str_out)

        # Replace the Client Hooks with our own. Since these are Mutable, this
        #   keeps them consistent across all Clients.
        client.hooks_notif = self.hooks_notif
        client.hooks_request = self.hooks_request

        self.clients.add(client)
        print("Client at {} has been assigned UUID {}.".format(client.host, client.id))
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
        except Exception as e:
            print("Server closing due to unexpected {}: {}".format(type(e).__name__, e))
        else:
            print("Server closing...")
        finally:
            try:
                asyncio.run(self.kill())
            except Exception:
                return
