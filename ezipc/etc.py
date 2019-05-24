import asyncio


def callback(coro):
    """Prepare a given Coroutine to interpret a Future as its Result."""
    async def callback_(future: asyncio.Future, *a, **kw):
        if future.done():
            return coro(future.result(), *a, **kw)

    return callback_
