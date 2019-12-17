import asyncio

from .util import callback_response, cleanup, echo, err, set_verbosity


def client_test(addr: str = "127.0.0.1", port: int = 9002, verb=4, CLIENTS=1):
    from .client import Client

    async def send_pings(_client):
        """One of the "main" Coroutines provided to `run_through()`. After the
            Client finishes its setup, it will call all Coroutines passed to
            `run_through()` in sequence, passing itself in; Thus, this Coroutine
            receives the Client and can operate it. Any Exceptions raised here
            will be caught by `run_through()`.
        """

        @callback_response
        def receive(result, remote):
            """Response handler Function. Assigned to a Future, and called by
                it when a Response with that UUID is received.
            """
            echo("tab", "PONG from {}: {}".format(remote, result))

        echo("info", "Sending Requests...")

        pongs = []

        for i in ["aaaa", "zxcv", "qwert", "wysiwyg"]:
            await asyncio.sleep(1)
            if not _client.alive:
                break

            # Send a Ping Request to the Server. Send the Callback by keyword
            #   arg so that it will be called as soon as the Future is ready.
            pongs.append(
                asyncio.create_task(
                    _client.remote.request(
                        "PING", [i], callback=receive, timeout=4
                    )
                )
            )
        await asyncio.sleep(1)
        pongs.append(
            asyncio.create_task(
                _client.remote.request("PING", [], callback=receive, timeout=4)
            )
        )

        try:
            res = await asyncio.gather(asyncio.sleep(1), *pongs, return_exceptions=True)
            total = len(pongs)
            win = total - res[1:].count(None)
            echo("info", "Successfuly ran {}/{} Pings.".format(win, total))
        except Exception as e:
            err("Failed to run Pings:", e)

    set_verbosity(verb)
    eventloop = asyncio.get_event_loop()

    x = [
        Client(addr, port).run_through(send_pings, loop=eventloop)
        for _ in range(CLIENTS)
    ]
    # `run_through()` may take any number of Coroutines as Arguments. They will
    #   be awaited, with the Client passed, sequentially.

    try:
        eventloop.run_until_complete(asyncio.gather(*x))

    except KeyboardInterrupt:
        print("INTERRUPT")

    finally:
        try:
            tasks = asyncio.Task.all_tasks()
            eventloop.run_until_complete(cleanup(tasks))
        finally:
            eventloop.close()


def server_test(addr: str = "127.0.0.1", port: int = 9002, verb=2, auto=False):
    from .server import Server

    set_verbosity(verb)
    Server(addr, port, auto).start()
    # If the Server will do nothing other than listen, it requires no more than
    #   this single call.
