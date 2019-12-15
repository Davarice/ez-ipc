"""Module providing interfaces for creation and reception of communications.

A (loose) implementation of the JSON-RPC 2.0 protocol.
https://www.jsonrpc.org/specification
"""

from abc import ABC, abstractmethod
from enum import IntEnum
from json import dumps, loads
from secrets import randbits
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
    Union,
)

from .exc import RemoteError


ID_PRE: str = "NaN"
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


ID: type = Optional[Union[int, str]]
ParamsRPC: type = Union[Dict[str, Any], List[Any]]


# Notification  ::  <jsonrpc>, <method>, [<params>]
# Request       ::  <jsonrpc>, <method>, [<params>], <id>
# Response      ::  <jsonrpc>, <<result>XOR<error>>, <id>


def _id_new() -> ID:
    return f"{ID_PRE}/{randbits(24):0>6X}"
    # return uuid4().hex


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
    def from_exception(cls, e: Exception) -> "Error":
        return cls(5, f"{type(e).__name__}: {str(e)}", e.args)

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

    def as_exception(self) -> RemoteError:
        return RemoteError.from_message(dict(self))

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
    def decode(cls, line: str) -> Iterator["Message"]:
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
                    yield Request(msg["method"], mid=msg["id"], **params)
                elif isinstance(params, list):
                    yield Request(msg["method"], *params, mid=msg["id"])
                else:
                    yield Request(msg["method"], mid=msg["id"])

            elif mtype is cls.RESPONSE:
                # noinspection PyArgumentList
                yield Response(
                    msg["id"], error=msg.get("error"), result=msg.get("result")
                )


class Message(ABC):
    jsonrpc = __version__
    mtype: JRPC = JRPC.NONE

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
    mtype = JRPC.NOTIF

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
        yield "jsonrpc", self.jsonrpc
        yield "method", self.method
        yield "params", self.params


class Request(Message):
    __slots__ = (
        "id",
        "method",
        "params",
    )
    mtype = JRPC.REQUEST

    @overload
    def __init__(self, method: str, *args, mid: ID = None):
        ...

    @overload
    def __init__(self, method: str, mid: ID = None, **kwargs):
        ...

    def __init__(self, method: str, *args, mid: ID = None, **kwargs):
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
        self.id: Final[ID] = mid or _id_new()

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
        yield "jsonrpc", self.jsonrpc
        yield "method", self.method
        yield "params", self.params
        yield "id", self.id


class Response(Message):
    __slots__ = (
        "error",
        "id",
        "result",
    )
    mtype = JRPC.RESPONSE

    @overload
    def __init__(self, request: Union[Request, ID]):
        ...

    @overload
    def __init__(self, request: Union[Request, ID], *, result: ParamsRPC):
        ...

    @overload
    def __init__(self, request: Union[Request, ID], *, error: Error):
        ...

    def __init__(
        self,
        request: Union[Request, ID],
        *,
        error: Error = None,
        result: ParamsRPC = None
    ):
        self.id: Final[ID] = request.id if isinstance(request, Request) else request

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
        yield "jsonrpc", self.jsonrpc

        if self.error is not None:
            yield "error", dict(self.error)
        else:
            yield "result", self.result or []

        yield "id", self.id


class Batch(List[Message]):
    def __init__(self, *a):
        super().__init__(a)

    def flat(self) -> List[Dict[str, Any]]:
        return [dict(msg) for msg in self]
