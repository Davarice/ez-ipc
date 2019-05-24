import asyncio

from .etc import callback
from .output import echo, set_verbosity


def client_test(addr: str = "127.0.0.1", port: int = 9002, verb=4, CLIENTS=1):
    from .client import Client

    async def send_pings(_client):
        """One of the "main" Coroutines provided to `run_through()`. After the
            Client finishes its setup, it will call all Coroutines passed to
            `run_through()` in sequence, passing itself in; Thus, this Coroutine
            receives the Client and can operate it. Any Exceptions raised here
            will be caught by `run_through()`.
        """

        @callback
        async def receive(future, remote):
            """Response handler Coroutine. Assigned to wait for a Response with
                a certain UUID, and called by the Listener when a Response with
                that UUID is received.
            """
            echo(
                "tab",
                "PONG from {}: {}".format(
                    remote, future.get("result") or future.result().get("error")
                ),
            )

        echo("", "Sending Requests...")

        pongs = []

        for i in ["aaaa", "zxcv", "qwert", "wysiwyg"]:
            await asyncio.sleep(1)
            if not _client.alive:
                return

            # Send a Ping Request to the Server. Send the Callback by keyword
            #   arg so that it will be called as soon as the Future is ready.
            pongs.append(await _client.remote.request("PING", [i], receive))

        print(pongs)

        # After the final line of the final Coroutine, the Client will end. One
        #   should take care that time is allotted to receive any Responses that
        #   may still be en route, unless one can be sure they are unimportant.
        await asyncio.sleep(1)
        await asyncio.gather(*pongs)

    set_verbosity(verb)
    eventloop = asyncio.get_event_loop()

    x = [
        Client(addr, port).run_through(send_pings, loop=eventloop)
        for _ in range(CLIENTS)
    ]
    # `run_through()` may take any number of Coroutines as Arguments. They will
    #   be awaited, with the Client passed, sequentially.

    try:
        # asyncio.wait(asyncio.gather(*x))
        eventloop.run_until_complete(asyncio.gather(*x))

    except KeyboardInterrupt:
        print("INTERRUPT")

    finally:
        try:
            tasks = asyncio.Task.all_tasks()
            for t in [t for t in tasks if not (t.done() or t.cancelled())]:
                eventloop.run_until_complete(t)
        finally:
            eventloop.close()


def server_test(addr: str = "127.0.0.1", port: int = 9002, verb=2, auto=False):
    from .server import Server

    set_verbosity(verb)
    Server(addr, port, auto).start()
    # If the Server will do nothing other than listen, it requires no more than
    #   this single call.
