import asyncio

from .output import echo, set_verbosity


def client_test(addr: str = "127.0.0.1", port: int = 9002, verb=2):
    from .client import Client

    async def go(_client):
        """One of the "main" Coroutines provided to `run_through()`. After the
            Client finishes its setup, it will call all Coroutines passed to
            `run_through()` in sequence, passing itself in; Thus, this Coroutine
            receives the Client and can operate it. Any Exceptions raised here
            will be caught by `run_through()`.
        """

        async def receive(data, conn):
            """Response handler Coroutine. Assigned to wait for a Response with
                a certain UUID, and called by the Listener when a Response with
                that UUID is received.
            """
            echo(
                "tab",
                "PONG from {}: {}".format(
                    conn, data.get("result") or data.get("error")
                ),
            )

        echo("", "Sending Requests...")

        for i in ["aaaa", "zxcv", "qwert", "wysiwyg"]:
            await asyncio.sleep(1)
            if not _client.alive:
                return

            # Send a Ping Request to the Server. Put the Callback in the final
            #   slot so it gets registered automatically.
            await _client.remote.request("PING", [i], receive)

        # After the final line of the final Coroutine, the Client will end. One
        #   should take care that time is allotted to handle any Responses that
        #   may still be en route.
        await asyncio.sleep(1)

    set_verbosity(verb)
    Client(addr, port).run_through(go)
    # `run_through()` may take any number of Coroutines as Arguments. They will
    #   be awaited, with the Client passed, sequentially.


def server_test(addr: str = "127.0.0.1", port: int = 9002, verb=2, auto=False):
    from .server import Server

    set_verbosity(verb)
    Server(addr, port, auto).start()
    # If the Server will do nothing other than listen, it requires no more than
    #   this single call.
