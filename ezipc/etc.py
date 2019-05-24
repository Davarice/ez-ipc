import asyncio


def future_callback(coro):
    """Prepare a given Coroutine to interpret a Future as its Result."""
    async def callback(future: asyncio.Future, *a, **kw):
        if future.done():
            return coro(future.result(), *a, **kw)

    return callback
