"""Module providing interfaces for creation and reception of communications.

A (loose) implementation of the JSON-RPC 2.0 protocol.
https://www.jsonrpc.org/specification
"""

import json
from typing import Tuple, Union
from uuid import uuid4


JSON_OPTS = {"separators": (",", ":")}
__version__ = "2.0"


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
    def new(code: int, message: str, data=None) -> dict:
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
    def parse_error(cls, data=None) -> dict:
        return cls.new(-32700, "Parse error", data)

    @classmethod
    def invalid_request(cls, data=None) -> dict:
        return cls.new(-32600, "Invalid Request", data)

    @classmethod
    def method_not_found(cls, data=None) -> dict:
        return cls.new(-32601, "Method not found", data)

    @classmethod
    def invalid_params(cls, data=None) -> dict:
        return cls.new(-32602, "Invalid params", data)

    @classmethod
    def server_error(cls, data=None) -> dict:
        return cls.new(-32603, "Internal error", data)


def make_notif(*args, **kwargs) -> bytes:
    """Make a Notification, to be sent without expectation of a Response.

    Contains:
        "jsonrpc" (str): Protocol specifier, must be "2.0".
        "method" (str): The name of the method to be invoked; Loosely, "why this
            request is being made".
        ["params"] (list, dict): The values to be used in the execution of the
            method specified.
    """
    req = _make(*args, **kwargs)

    return json.dumps(req, **JSON_OPTS).encode("utf-8")


def make_request(*args, **kwargs) -> Tuple[bytes, str]:
    """Make a Request, a message that will yield a Response.

    Contains ALL fields documented in `make_notif` above, PLUS:
        "id": Newly-generated UUID of the Request, for replication in Response.
    """
    req = _make(*args, **kwargs)
    mid = _id_new()
    req["id"] = mid

    return json.dumps(req, **JSON_OPTS).encode("utf-8"), mid


def make_response(mid: str, res: Union[dict, list]=None, err: dict = None) -> bytes:
    """Make a Response, to be sent in reply to a Request.

    Contains:
        "jsonrpc" (str): Protocol specifier, must be "2.0".
        Exactly ONE of:
            "result" (any): Whatever data should be sent back.
            "error" (dict): A Dict built by `Errors.new()`, contains data about
                what went wrong.
        "id": The UUID of the Request that prompted this Response.
    """
    resp = {"jsonrpc": __version__}
    if err:
        keys = list(err.keys())
        if not verify_error(keys):
            raise ValueError(
                "Error must have keys 'code', 'message', and, optionally, 'data'."
            )
        resp["error"] = err
    elif res:
        resp["result"] = res
    else:
        raise ValueError("Response MUST be provided either a Result or an Error.")
    resp["id"] = mid

    return json.dumps(resp, **JSON_OPTS).encode("utf-8")


def unpack(data: bytes) -> dict:
    return json.loads(data)


def verify_error(keys: list) -> bool:
    return keys == ["code", "message", "data"] or keys == ["code", "message"]


def verify_notif(keys: list, data: dict) -> bool:
    return data.get("jsonrpc", "") == __version__ and (
        keys == ["jsonrpc", "method", "params"] or keys == ["jsonrpc", "method"]
    )


def verify_request(keys: list, data: dict) -> bool:
    return data.get("jsonrpc", "") == __version__ and (
        keys == ["jsonrpc", "method", "params", "id"]
        or keys == ["jsonrpc", "method", "id"]
    )


def verify_response(keys: list, data: dict) -> bool:
    return data.get("jsonrpc", "") == __version__ and (
        keys == ["jsonrpc", "result", "id"] or keys == ["jsonrpc", "error", "id"]
    )
