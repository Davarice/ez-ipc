"""Module providing interfaces for creation and reception of communications.

A (loose) implementation of the JSON-RPC 2.0 protocol.
https://www.jsonrpc.org/specification
"""

from abc import ABC, abstractmethod
from enum import IntEnum
from json import dumps, loads
from typing import (
    Any,
    Dict,
    Final,
    FrozenSet,
    Iterator,
    List,
    Optional,
    overload,
    Tuple,
    TypedDict,
    Union,
)
from uuid import uuid4


JSON_OPTS = {"separators": (",", ":")}
__version__ = "2.0"


basic_: FrozenSet[str] = frozenset({"jsonrpc"})

id_: FrozenSet[str] = basic_ | frozenset({"id"})
method_: FrozenSet[str] = basic_ | frozenset({"method"})
params_: FrozenSet[str] = basic_ | frozenset({"params"})

err_sub: FrozenSet[str] = frozenset({"code", "message"})
err_sup: FrozenSet[str] = err_sub | frozenset({"data"})

notif_sup: FrozenSet[str] = method_ | params_
req_sub: FrozenSet[str] = id_ | method_
req_sup: FrozenSet[str] = req_sub | params_
res_sub: FrozenSet[str] = frozenset({"error", "result"})
res_sup: FrozenSet[str] = id_ | res_sub


ErrorRPC = TypedDict("ErrorRPC", dict(code=int, message=str, data=Any))
ParamsRPC = Union[Dict[str, Any], List[Any]]

NotifRPC = TypedDict("NotifRPC", dict(jsonrpc=str, method=str, params=ParamsRPC))
RequestRPC = TypedDict(
    "RequestRPC", dict(jsonrpc=str, method=str, params=ParamsRPC, id=str)
)
ResponseRPC = TypedDict(
    "ResponseRPC", dict(jsonrpc=str, result=ParamsRPC, error=ErrorRPC, id=str),
)


# Notification  ::  <jsonrpc>, <method>, [<params>]
# Request       ::  <jsonrpc>, <method>, [<params>], <id>
# Response      ::  <jsonrpc>, <<result>XOR<error>>, <id>


def _make(meth: str, *args, **kwargs) -> NotifRPC:
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


class Error(object):
    """Constructor for custom Error objects and shortcuts for pre-defined
        errors, as listed in section 5.1 of the JSON-RPC specification.
    """

    __slots__ = (
        "code",
        "data",
        "message",
    )

    def __init__(self, code: int, message: str, data: Any = None):
        self.code: int = code
        self.message: str = message
        self.data: Any = data

    @classmethod
    def parse_error(cls, data=None) -> "Error":
        return cls(-32700, "Parse error", data)

    @classmethod
    def invalid_request(cls, data=None) -> "Error":
        return cls(-32600, "Invalid Request", data)

    @classmethod
    def method_not_found(cls, data=None) -> "Error":
        return cls(-32601, "Method not found", data)

    @classmethod
    def invalid_params(cls, data=None) -> "Error":
        return cls(-32602, "Invalid params", data)

    @classmethod
    def server_error(cls, data=None) -> "Error":
        return cls(-32603, "Internal error", data)

    def __iter__(self) -> Iterator[Tuple[str, Any]]:
        """Make this Error into a Dict, to be sent as part of a Response to a
            failed Request.

        Contains:
            "code" (int): The identifier of the error type.
            "message" (str): Short description of the error.
            ["data"] (Any): A value containing further information.
        """
        yield "code", self.code
        yield "message", self.message

        if self.data is not None:
            yield "data", self.data

    def __repr__(self) -> str:
        return repr(dict(self))

    def __str__(self) -> str:
        return dumps(dict(self), **JSON_OPTS)


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

    return dumps(req, **JSON_OPTS)


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

    return dumps(req, **JSON_OPTS), mid


@overload
def make_response(mid: str, *, res: Union[dict, list, tuple] = None) -> str:
    ...


@overload
def make_response(mid: str, *, err: Error = None) -> str:
    ...


def make_response(
    mid: str, *, res: Union[dict, list, tuple] = None, err: Error = None
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
    if res and err:
        raise ValueError("Response must not contain both Result and Error.")
    elif err:
        err = dict(err)

        if err_sub <= set(err.keys()) <= err_sup:
            resp["error"] = err
        else:
            raise ValueError(
                "Error must have keys 'code', 'message', and, optionally, 'data'."
            )
    elif res is None:
        resp["result"] = []
        # raise ValueError("Response MUST be provided either a Result or an Error.")
    else:
        resp["result"] = res

    resp["id"] = mid
    return dumps(resp, **JSON_OPTS)


class Message(ABC):
    jsonrpc = __version__

    @abstractmethod
    def __iter__(self) -> Iterator[Tuple[str, Any]]:
        raise NotImplementedError

    def __repr__(self) -> str:
        return repr(dict(self))

    def __str__(self) -> str:
        return dumps(dict(self), **JSON_OPTS)


class Notification(Message):
    __slots__ = (
        "method",
        "params",
    )

    @overload
    def __init__(self, method: str, *args):
        ...

    @overload
    def __init__(self, method: str, **kwargs):
        ...

    def __init__(self, method: str, *args, **kwargs):
        if args and kwargs:
            raise ValueError(
                "JSONRPC Notification cannot mix Positional and Keyword Arguments."
            )
        elif args:
            self.params: ParamsRPC = list(args)
        elif kwargs:
            self.params: ParamsRPC = kwargs
        else:
            self.params: ParamsRPC = []

        self.method: Final[str] = method

    def __iter__(self) -> Iterator[Tuple[str, Any]]:
        # TODO
        ...


class Request(Message):
    __slots__ = (
        "id",
        "method",
        "params",
    )

    @overload
    def __init__(self, method: str, *args):
        ...

    @overload
    def __init__(self, method: str, **kwargs):
        ...

    # noinspection PyShadowingBuiltins
    def __init__(self, method: str, *args, id: str = None, **kwargs):
        if args and kwargs:
            raise ValueError(
                "JSONRPC Request cannot mix Positional and Keyword Arguments."
            )
        elif args:
            self.params: ParamsRPC = list(args)
        elif kwargs:
            self.params: ParamsRPC = kwargs
        else:
            self.params: ParamsRPC = []

        self.method: Final[str] = method
        self.id: Final[str] = id or _id_new()

    @overload
    def response(self) -> "Response":
        ...

    @overload
    def response(self, *, result: ParamsRPC) -> "Response":
        ...

    @overload
    def response(self, *, error: Error) -> "Response":
        ...

    def response(self, *, error: Error = None, result: ParamsRPC = None) -> "Response":
        # noinspection PyArgumentList
        return Response(self, error=error, result=result)
        # This is, normally, NOT A VALID CALL. However, we expect only one of
        #   these Keywords anyway, so if this raises an Exception, it should.

    def __iter__(self) -> Iterator[Tuple[str, Any]]:
        # TODO
        ...


class Response(Message):
    __slots__ = (
        "error",
        "id",
        "result",
    )

    @overload
    def __init__(self, request: Union[Request, str]):
        ...

    @overload
    def __init__(self, request: Union[Request, str], *, result: ParamsRPC):
        ...

    @overload
    def __init__(self, request: Union[Request, str], *, error: Error):
        ...

    def __init__(
        self,
        request: Union[Request, str],
        *,
        error: Error = None,
        result: ParamsRPC = None
    ):
        self.id: Final[str] = request.id if isinstance(request, Request) else request

        self.error: Optional[Error] = None
        self.result: Optional[ParamsRPC] = None

        if error or result:
            # noinspection PyArgumentList
            self.set(error=error, result=result)
            # This is, normally, NOT A VALID CALL. However, we expect only one
            #   of these Keywords anyway, so if this raises an Exception, it
            #   should.

    @overload
    def set(self, *, result: ParamsRPC) -> None:
        ...

    @overload
    def set(self, *, error: Error) -> None:
        ...

    def set(self, *, error: Error = None, result: ParamsRPC = None) -> None:
        if (error is None) is (result is None):
            # Method has been supplied both OR neither of the Arguments. This is
            #   an invalid call.
            raise ValueError("Response must be provided either an Error OR a Result.")
        else:
            self.error = error
            self.result = result

    def __bool__(self) -> Optional[bool]:
        if self.result is not None:
            return True
        elif self.error is not None:
            return False
        else:
            return None

    def __iter__(self) -> Iterator[Tuple[str, Any]]:
        # TODO
        ...


class Batch(List[Union[Notification, Request]]):
    def __init__(self, *a):
        super().__init__(a)

    def responses(self) -> Iterator[Response]:
        return (req.response() for req in self if isinstance(req, Request))


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

    @classmethod
    def decode(cls, line: str) -> Iterator[Message]:
        structure = loads(line)

        if isinstance(structure, dict):
            structure = [structure]

        for msg in structure:
            mtype = cls.check(msg)

            if mtype is cls.NOTIF:
                params = msg.get("params")

                if isinstance(params, dict):
                    yield Notification(msg["method"], **params)
                elif isinstance(params, list):
                    yield Notification(msg["method"], *params)
                else:
                    yield Notification(msg["method"])

            elif mtype is cls.REQUEST:
                params = msg.get("params")

                if isinstance(params, dict):
                    yield Request(msg["method"], **params)
                elif isinstance(params, list):
                    yield Request(msg["method"], *params)
                else:
                    yield Request(msg["method"])

            elif mtype is cls.RESPONSE:
                # noinspection PyArgumentList
                yield Response(
                    msg["id"], error=msg.get("error"), result=msg.get("result")
                )
