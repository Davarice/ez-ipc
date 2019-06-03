from functools import wraps
from os import strerror
from typing import Tuple, Union

from .protocol import Errors
from ..util import err


dl = Union[dict, list]

# Return Type Union, provided for Linting/SCA purposes.
handled = Union[
    None,  # Send no Response.
    int,  # Send a very basic Response. 0 for Result, nonzero for Error.
    dl,  # Send an implicit Result response with Data.
    Tuple[int, dl],  # Send a Result Response with Data.
    Tuple[int, str],  # Send an Error Response with a Message, but no Data.
    Tuple[int, str, dl],  # Send a full Error Response.
]


def request_handler(host, method: str):
    """Generate a Decorator which will wrap a Coroutine in a Response Handler
        and add a Callback Hook for a given RPC Method.
    """
    # Passed a JSON-RPC Method String like LOGIN or PING.

    def decorator(coro):
        """Wrap a Coroutine in a Wrapper that will allow it to send back a
            Response by simply Returning values.
        """
        # Coro should take data and remote, and return None, Int, or a Tuple.

        @wraps(coro)
        async def handle_response(data, remote):
            """Given Data and a Remote, execute the Coroutine provided above,
                and capture its Return. Then, use the Return to construct and
                send back a Response.
            """
            outcome: handled = await coro(data, remote)
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

        host.hooks_request[method] = handle_response
        return handle_response

    return decorator
