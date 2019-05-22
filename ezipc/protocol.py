"""Module providing interfaces for creation and reception of communications.

A (loose) implementation of the JSON-RPC 2.0 protocol.
https://www.jsonrpc.org/specification
"""

import json
from typing import Tuple
from uuid import uuid4


JSON_OPTS = {"separators": (",", ":")}


def _make(meth: str, *args, **kwargs) -> dict:
    if args and kwargs:
        raise ValueError("JSONRPC request must be either positional OR keywords.")
    elif args:
        params = list(args)
    elif kwargs:
        params = {**kwargs}
    else:
        params = None

    return {
            "jsonrpc": "2.0",
            "method": meth,
            "params": params,
        } if params else {
            "jsonrpc": "2.0",
            "method": meth,
        }


def id_new():
    return uuid4().hex


def error(code: int, message: str, data=None) -> dict:
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return err


def notif(*args, **kwargs) -> bytes:
    req = _make(*args, **kwargs)

    return json.dumps(
        req,
        **JSON_OPTS
    ).encode("utf-8")


def request(*args, **kwargs) -> Tuple[bytes, str]:
    req = _make(*args, **kwargs)
    mid = id_new()
    req["id"] = mid

    return json.dumps(
        req,
        **JSON_OPTS
    ).encode("utf-8"), mid


def response(mid: int, res=None, err: dict = None):
    resp = {"jsonrpc": "2.0"}
    if err:
        resp["error"] = err
    else:
        resp["result"] = res
    resp["id"] = mid

    return json.dumps(
        resp,
        **JSON_OPTS
    ).encode("utf-8")
