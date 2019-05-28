import asyncio
from collections import Counter
from datetime import datetime as dt
from typing import Union

from .common import Remote
from .etc import future_callback
from .output import echo, err, warn


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
        self.total_clients = 0
        self.total_sent = Counter(notif=0, request=0, response=0)
        self.total_recv = Counter(notif=0, request=0, response=0)

        self.hooks_notif = {}
        self.hooks_request = {}

    def _setup(self, *_a, **_kw):
        """Execute all prerequisites to running, before running. Meant to be
            overwritten by Subclasses.
        """

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

    async def broadcast(
        self, meth: str, params: Union[dict, list] = None, cb_broadcast=None
    ):
        if not self.remotes:
            return

        @future_callback
        def cb_confirm(data, remote):
            if data:
                echo("tab", "Broadcast '{}' received by {}.".format(meth, remote))
            else:
                warn("Broadcast '{}' NOT received by {}.".format(meth, remote))

        reqs = []
        for remote_ in self.remotes:
            reqs.append(
                (
                    remote_,
                    await remote_.request(meth, params, cb_broadcast or cb_confirm),
                )
            )

        for remote_, request in reqs:
            try:
                await asyncio.wait_for(request, 10)
            except Exception:
                warn("{} timed out.".format(remote_))
                self.drop(remote_)

    def drop(self, remote):
        self.total_sent.update(remote.total_sent)
        self.total_recv.update(remote.total_recv)
        self.remotes.remove(remote)

    async def encrypt_remote(self, remote):
        echo("info", "Starting Secure Connection with {}...".format(remote))
        try:
            if await asyncio.wait_for(remote.rsa_initiate(), 10):
                echo("win", "Secure Connection established with {}.".format(remote))
            else:
                warn("Failed to establish Secure Connection with {}.".format(remote))
        except asyncio.TimeoutError:
            warn("Failed to establish Secure Connection with {}.".format(remote))

    async def kill(self):
        for remote in self.remotes:
            await remote.terminate()
        self.remotes = []
        if self.server.is_serving():
            self.server.close()
            await self.server.wait_closed()
        echo("dcon", "Server closed.")

    async def open_connection(
        self, str_in: asyncio.StreamReader, str_out: asyncio.StreamWriter
    ):
        """Callback executed by AsyncIO when a Client contacts the Server."""
        echo(
            "con",
            "Incoming Connection from Client at `{}`.".format(
                str_out.get_extra_info("peername", ("Unknown Address", 0))[0]
            ),
        )
        remote = Remote(self.eventloop, str_in, str_out)
        self.total_clients += 1

        # Update the Client Hooks with our own.
        remote.hooks_notif.update(self.hooks_notif)
        remote.hooks_request.update(self.hooks_request)
        remote.startup = self.startup

        self.remotes.add(remote)
        echo(
            "diff",
            "Client at {} has been assigned UUID {}.".format(remote.host, remote.id),
        )

        rsa = self.eventloop.create_task(self.encrypt_remote(remote))
        try:
            await remote.loop()
        except:
            err("Connection to {} closed.")

        finally:
            try:
                await asyncio.wait_for(rsa, 3)
            except asyncio.TimeoutError:
                pass
            self.drop(remote)

    async def run(self, loop=None):
        """Server Coroutine. Does not setup or wrap the Server. Intended for use
            in instances where other things must be done, and the Server needs
            to be run properly asynchronously.
        """
        self.eventloop = loop or asyncio.get_event_loop()

        echo("info", "Running Server on {}:{}".format(self.addr, self.port))
        self.server = await asyncio.start_server(
            self.open_connection, self.addr, self.port, loop=self.eventloop
        )
        echo("win", "Ready to begin accepting Requests.")
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
            err("Server closing due to unexpected", e)
        else:
            echo("dcon", "Server closing...")
        finally:
            echo("info", "Served {} Clients.".format(self.total_clients))
            echo("info", "Sent:")
            echo(
                "tab",
                [
                    "> {} {}s".format(v, k.capitalize())
                    for k, v in self.total_sent.items()
                ],
            )
            echo("info", "Received:")
            echo(
                "tab",
                [
                    "> {} {}s".format(v, k.capitalize())
                    for k, v in self.total_recv.items()
                ],
            )
            try:
                asyncio.run(self.kill())
            except Exception:
                return
