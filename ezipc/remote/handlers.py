from asyncio import Future
from functools import wraps
from os import strerror
from typing import Callable, Coroutine, Tuple, TYPE_CHECKING, Union

from .protocol import Errors
from ..util import err

if TYPE_CHECKING:
    from . import Remote
else:
    from .stubs import Remote


dl = Union[dict, list]

# Return Type Union, provided for Linting/SCA purposes.
rpc_response = Union[
    None,  # Send no Response.
    int,  # Send a very basic Response. 0 for Result, nonzero for Error.
    dl,  # Send an implicit Result Response with Data.
    Tuple[int, dl],  # Send a Result Response with Data.
    Tuple[int, str],  # Send an Error Response with a Message, but no Data.
    Tuple[int, str, dl],  # Send a full Error Response.
]

# Define Signatures for Type Checking this horrific web of calls.
sig_req_cb = Callable[
    [dl, Remote], rpc_response
]  # Signature of the Coroutine defined under `@request_handler()`.
sig_req_handler = Callable[
    [dl, Remote], Coroutine
]  # Signature of the Coroutine returned by `@request_handler()`.

sig_req_cb_deco = Callable[
    [sig_req_cb], sig_req_handler
]  # Signature of the Decorator Function that a Coroutine defined under
   #    `@request_handler()` ACTUALLY gets passed to.

# ^ This is an utter nightmare to figure out. But it makes the Type Checker
#   incredibly smart about what you send where. Worth it.


def request_handler(host: Remote, method: str) -> sig_req_cb_deco:
    """Generate a Decorator which will wrap a Coroutine in a Request Handler
    and add a Callback Hook for a given RPC Method.

    For use with a Coroutine that **RECEIVES A REQUEST**, and **MUST SEND BACK**
    a message with a Reponse.

    :param Remote host: A Remote Object representing the IPC interface to
        another, possibly non-local, Process.
    :param str method: The JSON-RPC Method that the Decorator will hook the
        passed Coroutine to listen for, like LOGIN or PING

    :return: The Decorator Function that the next-defined Coroutine will
        *actually* be passed to.
    :rtype: Callable
    """

    def decorator(coro: sig_req_cb) -> sig_req_handler:
        """Wrap a Coroutine in a Wrapper that will allow it to send back a
        Response by simply Returning values.

        :param Callable coro: A Coroutine which will be passed the incoming
            Request Data should have one of a specific set of valid Signatures.

        :return: A Wrapped Coroutine which will Await the input Coroutine, and
            then send a Response Message back to the Remote that sent it, with a
            Result or Error attached as appropriate.
        :rtype: Callable[[Union[dict, list], Remote], Coroutine]
        """

        @wraps(coro)
        async def handle_request(data: dl, remote: Remote) -> None:
            """Given Data and a Remote, execute the Coroutine provided above,
            and capture its Return. Then, use the Return to construct and send
            back a Response.

            :param Union[dict, list] data: Data received from the Remote as part
                of the Request Message.
            :param Remote remote: A Remote Object representing the IPC interface
                to another, possibly non-local, Process.
            """
            outcome: rpc_response = await coro(data, remote)
            try:
                if outcome is not None:
                    if isinstance(outcome, int):
                        # Received a Return Status, but no Data. Make an empty
                        #   List to hold all the Data we do not have.
                        code: int = outcome
                        outcome: list = []

                    elif isinstance(outcome, (dict, list)):
                        # Received no Return Status, but received something that
                        #   is probably Data. Assume Success and send Response.
                        await remote.respond(
                            data["id"], data.get("method", method), res=outcome
                        )
                        return

                    elif isinstance(outcome, tuple):
                        # Received multiple returns. The first should be a
                        #   Status Code, but the rest will vary.
                        outcome: list = list(outcome)
                        code: int = outcome.pop(0)

                    else:
                        # Your Data is bad, and you should feel bad.
                        await remote.respond(
                            data["id"],
                            data.get("method", method),
                            err=Errors.new(
                                -32001,
                                "Server error",
                                [
                                    "Handler method '{}' returned erroneous "
                                    "Type. Contact Project Maintainer.".format(
                                        coro.__name__
                                    )
                                ],
                            ),
                        )
                        return

                    if code != 0:
                        # ERROR. Send an Error Response.
                        if outcome:
                            # Retrieve further information.
                            message = outcome.pop(0)
                            errdat = outcome.pop(0) if outcome else None
                        else:
                            # No further information available.
                            try:
                                message = strerror(code)
                            except ValueError:
                                message = "Unknown error {}".format(code)

                            errdat = None

                        await remote.respond(
                            data["id"],
                            data.get("method", method),
                            err=Errors.new(code, message, errdat),
                        )
                    else:
                        # No error. Send a Result Response.
                        resdat = outcome.pop(0) if outcome else []

                        await remote.respond(
                            data["id"], data.get("method", method), res=resdat
                        )
                else:
                    # Returned None, therefore Return None.
                    return

            except Exception as e:
                # The whole system is on fire.
                err(
                    "Exception raised by Request Handler"
                    " for '{}':".format(coro.__name__),
                    e,
                )
                if "id" in data:
                    await remote.respond(
                        data["id"],
                        data.get("method", method),
                        err=Errors.new(121, type(e).__name__, [str(e)]),
                    )

        host.hooks_request[method] = handle_request
        return handle_request

    return decorator


sig_win = Callable[
    [dl, Remote], None
]  # Signature of the Function to be dispatched if the Future returns Result.
sig_fail = Callable[
    [Exception, Remote], None
]  # Signature of the Function...returns Exception.
sig_cancel = Callable[
    [], None
]  # Signature of...Cancelled.


def response_handler(
    remote: Remote,
    *,
    win: sig_win = None,
    fail: sig_fail = None,
    cancel: sig_cancel = None,
) -> Callable[[Future], None]:
    """Generate a Callback Function that will dispatch the outcome of a Future
    to one of up to three other Functions depending on whether the passed
    Future was successful.

    For use with Synchronous Functions that **RECEIVE A RESPONSE** after a
    Request has been sent.

    :param Remote remote: A Remote Object representing the IPC interface to
        another, possibly non-local, Process.
    :type remote: Remote
    :param Callable win: A Function to be dispatched the
        Result of a Future if the Future comes back successful.
    :param Callable fail: A Function to be dispatched
        the Exception returned by a Future which is not successful.
    :param Callable cancel: A Function to be dispatched with no
        arguments if the Future is Cancelled.

    :return: A Callback Function which receives a Future and dispatches it to
        one of the provided Functions.
    :rtype: Callable[[Future], None]
    """

    def callback(future: Future) -> None:
        if not future.done():
            # Not done? Cant do anything.
            return
        elif future.cancelled():
            # Cancelled? Dispatch. No args.
            if cancel:
                cancel()
        else:
            ex = future.exception()
            if ex is None:
                # No Exception? Dispatch the Result.
                if win:
                    win(future.result(), remote)
            else:
                # Exception? Dispatch the Exception.
                if fail:
                    fail(ex, remote)

    return callback
