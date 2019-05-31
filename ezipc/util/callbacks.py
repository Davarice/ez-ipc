"""Module defining Callback functions to be executed with Futures."""

import asyncio
from functools import wraps


def callback_response(func):
    """Prepare a given Function to interpret a Future as its Result instead, so
        that the Function does not need to worry about Exceptions.

    NOTE: If the Future was set an Exception, or cancelled, it will be IGNORED
        by any Callback that uses this Decorator.
    """

    @wraps(func)
    def callback(future: asyncio.Future, remote=None):
        if future.done() and not (future.cancelled() or future.exception()):
            return func(future.result(), remote=remote)

    return callback
