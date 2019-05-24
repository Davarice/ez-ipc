import asyncio


def future_callback(func):
    """Prepare a given Function to interpret a Future as its Result instead."""

    def callback(future: asyncio.Future, *a, **kw):
        if future.done():
            return func(future.result(), *a, **kw)

    return callback
