import asyncio
from datetime import datetime as dt

from .common import Remote
from .output import echo, err


class Server:
    """The Server is the component of the Client/Server Model that waits for
        input from a Client, and then operates on it. The Server can interface
        with multiple Clients at the same time, and may even facilitate
        communications between two Clients.

    As the more passive component, the Server will spend most of its time waiting.
    """

    def __init__(self, addr: str = "", port: int = 9002, autopublish=False):
        if autopublish:
            # TODO: Find the network address of this machine.
            pass
        elif not addr:
            addr = "127.0.0.1"

        self.addr = addr
        self.port = port

        self.eventloop = None
        self.remotes = set()
        self.server = None
        self.startup = dt.utcnow()

        self.hooks_notif = {}
        self.hooks_request = {}

    def _setup(self, *_a, **_kw):
        """Execute all prerequisites to running, before running. Meant to be
            overwritten by Subclasses.
        """

        async def cb_pong(data, conn: Remote):
            await conn.respond(
                data["id"], data["method"], res={"method": "PONG", "params": data["params"]}
            ) if "params" in data else conn.respond(
                data["id"], data["method"], res={"method": "PONG", "params": None}
            )

        self.hook_request("PING", cb_pong)

        async def cb_time(data, conn: Remote):
            await conn.respond(
                data.get("id", "0"), res={"startup": self.startup.timestamp()}
            )

        self.hook_request("TIME", cb_time)

    def hook_notif(self, method: str, func):
        """Signal to the Remote that `func` is waiting for Notifications of the
            provided `method` value.
        """
        self.hooks_notif[method] = func

    def hook_request(self, method: str, func):
        """Signal to the Remote that `func` is waiting for Requests of the
            provided `method` value.
        """
        self.hooks_request[method] = func

    async def broadcast(self, meth: str, params=None):
        if not self.remotes:
            return

        async def cb_broadcast(data, remote):
            if "result" in data:
                echo("tab", "Broadcast received by {}.".format(remote))

        for conn, req in [
            (conn, conn.request(meth, params, cb_broadcast))
            for conn in self.remotes
            if not conn.outstr.is_closing()
        ]:
            try:
                await req
            except Exception:
                err("{} is not responding.".format(conn))
                try:
                    asyncio.ensure_future(req).cancel()
                    await conn.close()
                finally:
                    self.remotes.remove(conn)

    def drop(self, remote):
        pass

    async def kill(self):
        for remote in self.remotes:
            await remote.terminate()
        self.remotes = []
        if self.server.is_serving():
            self.server.close()
            await self.server.wait_closed()
        echo("", "Server closed.")

    async def open_connection(
        self, str_in: asyncio.StreamReader, str_out: asyncio.StreamWriter
    ):
        """Callback executed by AsyncIO when a Client contacts the Server."""
        echo("con",
            "Incoming Connection from Client at `{}`.".format(
                str_out.get_extra_info("peername", ("Unknown Address", 0))[0]
            )
        )
        remote = Remote(self.eventloop, str_in, str_out)

        # Replace the Client Hooks with our own. Since these are Mutable, this
        #   keeps them consistent across all Clients.
        remote.hooks_notif = self.hooks_notif
        remote.hooks_request = self.hooks_request
        remote.startup = self.startup

        # for r_ in self.remotes.copy():
        #     if not r_ or r_.outstr.is_closing():
        #         self.remotes.remove(r_)

        self.remotes.add(remote)
        await self.broadcast("CENSUS", {"client_count": len(self.remotes)})
        echo("diff",
            "Client at {} has been assigned UUID {}.".format(remote.host, remote.id)
        )
        try:
            await remote.loop()
        except:
            err("Connection to {} closed.")
        finally:
            self.remotes.remove(remote)

    async def run(self, loop=None):
        """Server Coroutine. Does not setup or wrap the Server. Intended for use
            in instances where other things must be done, and the Server needs
            to be run properly asynchronously.
        """
        self.eventloop = loop or asyncio.get_event_loop()

        echo("", "Running Server on {}:{}".format(self.addr, self.port))
        self.server = await asyncio.start_server(
            self.open_connection,
            self.addr,
            self.port,
            loop=self.eventloop,
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
            err("INTERRUPTED. Server closing...")
        except Exception as e:
            err("Server closing due to unexpected {}: {}".format(type(e).__name__, e))
        else:
            echo("", "Server closing...")
        finally:
            try:
                asyncio.run(self.kill())
            except Exception:
                return
