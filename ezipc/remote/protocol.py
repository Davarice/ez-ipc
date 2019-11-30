"""Module providing interfaces for creation and reception of communications.

A (loose) implementation of the JSON-RPC 2.0 protocol.
https://www.jsonrpc.org/specification
"""

from enum import IntEnum
import json
from typing import Hashable, overload, Tuple, Type, TypedDict, Union
from uuid import uuid4


JSON_OPTS = {"separators": (",", ":")}
__version__ = "2.0"


basic_ = frozenset({"jsonrpc"})

id_ = basic_ | frozenset({"id"})
method_ = basic_ | frozenset({"method"})
params_ = basic_ | frozenset({"params"})

err_sub = frozenset({"code", "message"})
err_sup = err_sub | frozenset({"data"})

notif_sup = method_ | params_
req_sub = id_ | method_
req_sup = req_sub | params_
res_sub = frozenset({"error", "result"})
res_sup = id_ | res_sub


ErrorRPC: Type[dict] = TypedDict("ErrorRPC", dict(code=int, message=str, data=Hashable))


def _make(meth: str, *args, **kwargs) -> dict:
    if args and kwargs:
        raise ValueError("JSONRPC request must be either positional OR keywords.")
    elif args:
        params = list(args)
    elif kwargs:
        params = {**kwargs}
    else:
        params = None

    return (
        {"jsonrpc": __version__, "method": meth, "params": params}
        if params is not None
        else {"jsonrpc": __version__, "method": meth}
    )


def _id_new() -> str:
    return uuid4().hex


def check_version(v: str) -> bool:
    return v == __version__


class Errors:
    """Constructor for custom Error objects and shortcuts for pre-defined
        errors, as listed in section 5.1 of the JSON-RPC specification.
    """

    @staticmethod
    def new(code: int, message: str, data: Hashable = None) -> ErrorRPC:
        """Make an Error, to be sent in a Response to a failed Request.

        Contains:
            "code" (int): The identifier of the error type.
            "message" (str): Short description of the error.
            ["data"] (any): A value containing further information.
        """
        err = {"code": code, "message": message}
        if data is not None:
            err["data"] = data
        return err

    @classmethod
    def parse_error(cls, data: Hashable = None) -> ErrorRPC:
        return cls.new(-32700, "Parse error", data)

    @classmethod
    def invalid_request(cls, data: Hashable = None) -> ErrorRPC:
        return cls.new(-32600, "Invalid Request", data)

    @classmethod
    def method_not_found(cls, data: Hashable = None) -> ErrorRPC:
        return cls.new(-32601, "Method not found", data)

    @classmethod
    def invalid_params(cls, data: Hashable = None) -> ErrorRPC:
        return cls.new(-32602, "Invalid params", data)

    @classmethod
    def server_error(cls, data: Hashable = None) -> ErrorRPC:
        return cls.new(-32603, "Internal error", data)


@overload
def make_notif(meth: str, *args) -> str:
    ...


@overload
def make_notif(meth: str, **kwargs) -> str:
    ...


def make_notif(meth: str, *args, **kwargs) -> str:
    """Make a Notification, to be sent without expectation of a Response.

    Contains:
        "jsonrpc" (str): Protocol specifier, must be "2.0".
        "method" (str): The name of the method to be invoked; Loosely, "why this
            request is being made".
        ["params"] (list, dict): The values to be used in the execution of the
            method specified.
    """
    req = _make(meth, *args, **kwargs)

    return json.dumps(req, **JSON_OPTS)


@overload
def make_request(meth: str, *args) -> Tuple[str, str]:
    ...


@overload
def make_request(meth: str, **kwargs) -> Tuple[str, str]:
    ...


def make_request(meth: str, *args, **kwargs) -> Tuple[str, str]:
    """Make a Request, a message that will yield a Response.

    Contains ALL fields documented in `make_notif` above, PLUS:
        "id": Newly-generated UUID of the Request, for replication in Response.
    """
    req = _make(meth, *args, **kwargs)
    mid = _id_new()
    req["id"] = mid

    return json.dumps(req, **JSON_OPTS), mid


@overload
def make_response(mid: str, *, res: Union[dict, list] = None) -> str:
    ...


@overload
def make_response(mid: str, *, err: ErrorRPC = None) -> str:
    ...


def make_response(
    mid: str, *, res: Union[dict, list] = None, err: ErrorRPC = None
) -> str:
    """Make a Response, to be sent in reply to a Request.

    Contains:
        "jsonrpc" (str): Protocol specifier, must be "2.0".
        Exactly ONE of:
            "result" (dict or list): Whatever data should be sent back.
            "error" (dict): A Dict built by `Errors.new()`, contains data about
                what went wrong.
        "id": The UUID of the Request that prompted this Response.
    """
    resp = {"jsonrpc": __version__}
    if err:
        if not (err_sub <= set(err.keys()) <= err_sup):
            raise ValueError(
                "Error must have keys 'code', 'message', and, optionally, 'data'."
            )
        resp["error"] = err
    elif res is not None:
        resp["result"] = res
    else:
        resp["result"] = []
        # raise ValueError("Response MUST be provided either a Result or an Error.")
    resp["id"] = mid

    return json.dumps(resp, **JSON_OPTS)


class JRPC(IntEnum):
    NONE = 0
    NOTIF = 1
    REQUEST = 2
    RESPONSE = 3

    @classmethod
    def check(cls, data: dict) -> "JRPC":
        if data.get("jsonrpc") != __version__:
            return cls.NONE
        keys = frozenset(data.keys())

        if id_ < keys:
            # Either a Request or a Response.
            if req_sub <= keys <= req_sup:
                return cls.REQUEST
            elif res_sub & keys and keys <= res_sup:
                return cls.RESPONSE

        elif method_ <= keys <= notif_sup:
            # A Notification.
            return cls.NOTIF

        return cls.NONE
