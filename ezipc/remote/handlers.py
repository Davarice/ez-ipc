from asyncio import Future
from functools import wraps
from inspect import signature
from typing import Callable, Dict, Tuple, TYPE_CHECKING, TypeVar, Union

from .protocol import Notification, Request

if TYPE_CHECKING:
    from . import Remote
else:
    Remote = TypeVar("Remote")


dl = TypeVar("dl", dict, list)

# Return Type Union, provided for Linting/SCA purposes.
rpc_response: type = Union[
    None,  # Send no Response.
    int,  # Send a very basic Response. 0 for Result, nonzero for Error.
    dl,  # Send an implicit Result Response with Data.
    Tuple[int, dl],  # Send a Result Response with Data.
    Tuple[int, str],  # Send an Error Response with a Message, but no Data.
    Tuple[int, str, dl],  # Send a full Error Response.
]


def notif_handler(hooks: Dict[str, Callable], method: str) -> Callable:
    """Generate a Decorator which will wrap a Function in a Request Handler
    and add a Callback Hook for a given RPC Method.

    For use with a Function that **RECEIVES A NOTIFICATION**.

    :param dict hooks: A Mapping associating String Methods to their respective
        Callables.
    :param str method: The JSON-RPC Method that the Decorator will hook the
        passed Function to listen for, like LOGIN or PING.

    :return: The Decorator Function that the next-defined Function will
        *actually* be passed to.
    :rtype: Callable
    """

    def decorator(func: Callable) -> Callable:
        """Wrap a Function in a Wrapper that will allow it to send back a
        Response by simply Returning values.

        :param Callable func: A Function which will be passed the incoming
            Request Data should have one of a specific set of valid Signatures.

        :return: A Wrapped Function which will call the input Function, and
            then send a Response Message back to the Remote that sent it, with a
            Result or Error attached as appropriate.
        :rtype: Callable[[Union[dict, list], Remote], Callable]
        """

        @wraps(func)
        def handle_notif(notif: Notification, remote: Remote):
            """Given Data and a Remote, execute the Function provided above,
            and capture its Return.

            :param Notification notif: Data received from the Remote as the
                Notification Message.
            :param Remote remote: A Remote Object representing the IPC interface
                to another, possibly non-local, Process.
            """
            if len(signature(func).parameters) > 1:
                return func(notif.params, remote)
            else:
                return func(notif.params)

        hooks[method] = handle_notif
        return handle_notif

    return decorator


def request_handler(hooks: Dict[str, Callable], method: str) -> Callable:
    """Generate a Decorator which will wrap a Function in a Request Handler
    and add a Callback Hook for a given RPC Method.

    For use with a Function that **RECEIVES A REQUEST**, and **MUST SEND BACK**
    a message with a Reponse.

    :param dict hooks: A Mapping associating String Methods to their respective
        Callables.
    :param str method: The JSON-RPC Method that the Decorator will hook the
        passed Function to listen for, like LOGIN or PING.

    :return: The Decorator Function that the next-defined Function will
        *actually* be passed to.
    :rtype: Callable
    """

    def decorator(func: Callable) -> Callable:
        """Wrap a Function in a Wrapper that will allow it to send back a
        Response by simply Returning values.

        :param Callable func: A Function which will be passed the incoming
            Request Data should have one of a specific set of valid Signatures.

        :return: A Wrapped Function which will call the input Function, and
            then send a Response Message back to the Remote that sent it, with a
            Result or Error attached as appropriate.
        :rtype: Callable[[Union[dict, list], Remote], Callable]
        """

        @wraps(func)
        def handle_request(request: Request, remote: Remote):
            """Given Data and a Remote, execute the Function provided above,
            and capture its Return.

            :param Request request: Data received from the Remote as the Request
                Message.
            :param Remote remote: A Remote Object representing the IPC interface
                to another, possibly non-local, Process.
            """
            if len(signature(func).parameters) > 1:
                return func(request.params, remote)
            else:
                return func(request.params)

            # res: Union[Coroutine, rpc_response] = coro(request.params, host)
            # while isinstance(res, Coroutine):
            #     # This is *probably* a Coroutine, but it may just be a Function.
            #     #   Check before blindly trying to Await.
            #     res = await res
            # outcome: rpc_response = res
            #
            # try:
            #     if outcome is not None:
            #         ...
            #
            #         # if isinstance(outcome, int):
            #         #     # Received a Return Status, but no Data. Make an empty
            #         #     #   List to hold all the Data we do not have.
            #         #     code: int = outcome
            #         #     outcome: list = []
            #         #
            #         # elif isinstance(outcome, (dict, list)):
            #         #     # Received no Return Status, but received something that
            #         #     #   is probably Data. Assume Success and send Response.
            #         #     return request.response(result=outcome)
            #         #
            #         # elif isinstance(outcome, tuple):
            #         #     # Received multiple Returns. The first should be a
            #         #     #   Status Code, but the rest will vary.
            #         #     outcome: list = list(outcome)
            #         #     code: int = outcome.pop(0)
            #         #
            #         # else:
            #         #     # Your Data is bad, and you should feel bad.
            #         #     return request.response(
            #         #         error=Error(
            #         #             -32001,
            #         #             "Server error",
            #         #             [
            #         #                 f"Handler method {coro.__name__!r} returned erroneous "
            #         #                 f"Type. Contact Project Maintainer."
            #         #             ],
            #         #         ),
            #         #     )
            #
            #         # if code != 0:
            #         #     # ERROR. Send an Error Response.
            #         #     if outcome:
            #         #         # Retrieve further information.
            #         #         message = outcome.pop(0)
            #         #         errdat = outcome.pop(0) if outcome else None
            #         #     else:
            #         #         # No further information available.
            #         #         try:
            #         #             message = strerror(code)
            #         #         except ValueError:
            #         #             message = f"Unknown error {code}"
            #         #
            #         #         errdat = None
            #         #
            #         #     return request.response(error=Error(code, message, errdat))
            #         # else:
            #         #     # No error. Send a Result Response.
            #         #     resdat = outcome.pop(0) if outcome else []
            #         #
            #         #     return request.response(result=resdat)
            #     else:
            #         # Returned None, therefore Return None.
            #         return request.response()
            #
            # except Exception as e:
            #     # The whole system is on fire.
            #     err(f"Exception raised by Request Handler for {coro.__name__!r}:", e)
            #     return request.response(error=Error(121, type(e).__name__, [str(e)]))

        hooks[method] = handle_request
        return handle_request

    return decorator


def response_handler(
    remote: Remote,
    *,
    win: Callable = None,
    fail: Callable = None,
    cancel: Callable = None,
) -> Callable[[Future], None]:
    """Generate a Callback Function that will dispatch the outcome of a Future
    to one of up to three other Functions depending on whether the passed
    Future was successful.

    For use with Synchronous Functions that **RECEIVE A RESPONSE** after a
    Request has been sent.

    :param Remote remote: A Remote Object representing the IPC interface to
        another, possibly non-local, Process.
    :param Callable win: A Function to be dispatched the Result of a Future if
        the Future comes back successful.
    :param Callable fail: A Function to be dispatched the Exception returned by
        a Future which is not successful.
    :param Callable cancel: A Function to be dispatched with no arguments if the
        Future is Cancelled.

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
            if cancel is not None:
                cancel()
        else:
            ex = future.exception()
            if ex is None:
                # No Exception? Dispatch the Result.
                if win is not None:
                    win(future.result(), remote)
            else:
                # Exception? Dispatch the Exception.
                if fail is not None:
                    fail(ex, remote)

    return callback
