import asyncio


def _deco(decorator):
    """Wrap a Decorator so that the Function it returns is given the same Name
        and Docstring as the Function it was given.

    Writing this gave me a headache. Worth it? Probably not. But whatever.
    """
    def decorated(function):
        callback = decorator(function)

        callback.__doc__ = function.__doc__
        callback.__name__ = function.__name__

        return callback

    return decorated


@_deco
def callback_response(func):
    """Prepare a given Function to interpret a Future as its Result instead, so
        that the Function does not need to worry about Exceptions.

    NOTE: If the Future was set an Exception, or cancelled, it will be IGNORED
        by any Callback that uses this Decorator.
    """

    def callback(future: asyncio.Future, remote=None):
        if future.done() and not (future.cancelled() or future.exception()):
            return func(future.result(), remote=remote)

    return callback
