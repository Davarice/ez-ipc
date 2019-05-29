"""Package defining a superclass with methods common to Clients and Servers.

This is where the real work gets done.
"""

from asyncio import (
    AbstractEventLoop,
    CancelledError,
    create_task,
    Future,
    gather,
    IncompleteReadError,
    StreamReader,
    StreamWriter,
    Task,
    TimeoutError,
    wait_for,
)
from collections import Counter
from datetime import datetime as dt
from functools import partial
from json import JSONDecodeError
from typing import Dict, List, Union
from uuid import uuid4

from .protocol import (
    Errors,
    make_notif,
    make_request,
    make_response,
    unpack,
    verify_notif,
    verify_request,
    verify_response,
)
from .connection import Connection, CryptoError
from .exc import RemoteError
from ..util.output import echo, err as err_, warn


class Remote:
    def __init__(self, eventloop, instr, outstr, group: set = None):
        self.eventloop: AbstractEventLoop = eventloop
        self.instr: StreamReader = instr
        self.outstr: StreamWriter = outstr
        self.connection = Connection(instr, outstr)
        self.addr, self.port = self.outstr.get_extra_info("peername", ("0.0.0.0", 0))

        self.hooks_notif = {}  # {"method": function()}
        self.hooks_request = {}  # {"method": function()}

        self.futures: Dict[str, Future] = {}
        self.tasks: List[Task] = []
        self.total_sent: Counter = Counter(byte=0, notif=0, request=0, response=0)
        self.total_recv: Counter = Counter(byte=0, notif=0, request=0, response=0)

        self.group: set = group
        self.id: str = hex(
            (uuid4().int + self.port + sum([int(s) for s in self.addr.split(".")]))
            % 16 ** 3
        )[2:]

        now = dt.utcnow()
        self.opened: dt = now
        self.startup: dt = now
        self._add_default_hooks()

    @property
    def host(self) -> str:
        return "{}:{}".format(self.addr, self.port)

    @property
    def is_secure(self) -> bool:
        return bool(self.connection.can_encrypt and self.connection.box)

    def __str__(self):
        return "Remote " + self.id

    def _add_default_hooks(self):
        async def cb_ping(data: dict, remote: Remote):
            await remote.respond(
                data["id"], data["method"], res=data.get("params") or [None]
            )

        self.hook_request("PING", cb_ping)

        async def cb_rsa_exchange(data: dict, remote: Remote):
            if remote.connection.can_encrypt:
                echo(
                    "info",
                    [
                        "Receiving a request for Secure Connection. Sending Key.",
                        "(The connection is not encrypted yet.)",
                    ],
                )
                remote.connection.add_key(data.get("params", [None])[0])
                await remote.respond(
                    data["id"], data["method"], res=[remote.connection.key]
                )
            else:
                err_("Cannot establish a Secure Connection.")
                await remote.respond(data["id"], data["method"], res=[False])

        self.hook_request("RSA.EXCH", cb_rsa_exchange)

        async def cb_rsa_confirm(data: dict, remote: Remote):
            if remote.connection.can_activate():
                await remote.respond(data["id"], data["method"], res=[True])
                remote.connection.begin_encryption()
                echo("win", "Connection Secured by RSA Key Exchange.")

        self.hook_request("RSA.CONF", cb_rsa_confirm)

    async def enable_rsa(self) -> bool:
        if not self.connection.can_encrypt or self.connection.box:
            return False
        else:
            # Ask the remote Host for its Public Key, while providing our own.
            key = (await self.request_wait("RSA.EXCH", [self.connection.key], [None]))[
                0
            ]

            if key:
                self.connection.add_key(key)
            else:
                return False

            # Double check that the remote Host is ready to start encrypting.
            if (await self.request_wait("RSA.CONF", [True], [False]))[0]:
                # We can now start using encryption.
                self.connection.begin_encryption()
                return True
            else:
                # Something went wrong. Do NOT switch to encryption.
                return False

    async def get_line(self) -> str:
        line: str = await self.connection.read()
        if line == b"":
            raise ConnectionResetError("Stream closed by remote host.")
        else:
            return line

    async def process_line(self, line: str):
        try:
            data = unpack(line)
        except JSONDecodeError as e:
            warn("Invalid JSON received from {}.".format(self))
            await self.respond("0", err=Errors.parse_error(str(e)))
            return
        except UnicodeDecodeError:
            warn("Corrupt data received from {}.".format(self))
            return

        keys = list(data.keys())
        if verify_response(keys, data):
            # Message is a RESPONSE.
            echo("recv", "Receiving a Response from {}...".format(self))
            self.total_recv["response"] += 1
            mid = data["id"]
            if mid in self.futures:
                # Something is waiting for this message.
                future: Future = self.futures[mid]
                del self.futures[mid]

                if future.done():
                    warn(
                        "Received a Response for a closed Future. UUID: {}".format(mid)
                    )
                elif future.cancelled():
                    warn(
                        "Received a Response for a cancelled Future. UUID: {}".format(
                            mid
                        )
                    )
                else:
                    # We need to fulfill this Future now.
                    if "error" in data:
                        # Server sent an Error Response. Forward it to the Future.
                        e = RemoteError(
                            data["error"]["code"],
                            data["error"]["message"],
                            data["error"]["data"] if "data" in data["error"] else None,
                            mid,
                        )
                        future.set_exception(e)
                    else:
                        # Server sent a Result Response. Give it to the Future.
                        future.set_result(data["result"])
            else:
                # Nothing is waiting for this message. Make a note and move on.
                warn("Received an unsolicited Response. UUID: {}".format(mid))

        elif verify_request(keys, data):
            # Message is a REQUEST.
            echo(
                "recv",
                "Receiving a '{}' Request from {}...".format(data["method"], self),
            )
            self.total_recv["request"] += 1
            if data["method"] in self.hooks_request:
                # We know where to send this type of Request.
                func = self.hooks_request[data["method"]]
                # await func(data, self)
                tsk = create_task(func(data, self))
                self.tasks.append(tsk)
            else:
                # We have no hook for this method; Return an Error.
                await self.respond(
                    data["id"], err=Errors.method_not_found(data.get("method"))
                )

        elif verify_notif(keys, data):
            # Message is a NOTIFICATION.
            echo(
                "recv",
                "Receiving a '{}' Notification from {}...".format(data["method"], self),
            )
            self.total_recv["notif"] += 1
            if data["method"] == "TERM":
                # The connection is being explicitly terminated.
                raise ConnectionResetError(
                    data["params"]["reason"] or "Connection terminated by peer."
                )
            elif data["method"] in self.hooks_notif:
                # We know where to send this type of Notification.
                func = self.hooks_notif[data["method"]]
                self.tasks.append(create_task(func(data, self)))

        else:
            # Message is not a valid JSON-RPC structure. If we can find an ID,
            #   send a Response containing an Error and a frowny face.
            echo("", "Received an invalid Message from {}".format(self))
            if "id" in data:
                await self.respond(data["id"], err=Errors.invalid_request(keys))

    def hook_notif(self, method: str, func):
        """Signal to the Remote that `func` is waiting for Notifications of the
            provided `method` value.
        """
        self.hooks_notif[method] = func

    def hook_request(self, method: str, func):
        """Signal to the Remote that `func` is waiting for Requests of the
            provided `method` value.
        """
        self.hooks_request[method] = func

    def close(self):
        self.total_recv["byte"] = self.connection.total_recv
        self.total_sent["byte"] = self.connection.total_sent

        for coro in self.tasks:
            # Cancel all running Tasks.
            if coro:
                coro.cancel()

        if self.group is not None and self in self.group:
            # Remove self from Client Set, if possible.
            self.group.remove(self)

        if self.outstr.can_write_eof() and not self.outstr.is_closing():
            # Send an EOF, if possible.
            self.outstr.write_eof()

        # Finally, close the Stream.
        self.outstr.close()

    async def loop(self):
        try:
            while True:
                try:
                    line = await self.get_line()
                except CryptoError as e:
                    warn(
                        "Decryption from {} failed: {} - {}".format(
                            self, type(e).__name__, e
                        )
                    )
                else:
                    await self.process_line(line)
        except IncompleteReadError:
            err_("Connection with {} cut off.".format(self))
        except EOFError:
            err_("Connection with {} failed: Stream ended.".format(self))
            self.close()
        except ConnectionError as e:
            echo("dcon", "Connection with {} closed: {}".format(self, e))
            self.close()
        except CancelledError:
            # err_("Listening to {} was cancelled.".format(self))
            pass
        except Exception as e:
            err_("Connection with {} failed:".format(self), e)
        finally:
            try:
                tasks = gather(*self.tasks)
                self.tasks = []
                await tasks
            finally:
                self.total_recv["byte"] = self.connection.total_recv
                self.total_sent["byte"] = self.connection.total_sent

    async def notif(self, meth: str, params: Union[dict, list] = None, nohandle=False):
        """Assemble and send a JSON-RPC Notification with the given data."""
        try:
            echo("send", "Sending a '{}' Notification to {}.".format(meth, self))
            self.total_sent["notif"] += 1
            if type(params) == dict:
                await self.send(make_notif(meth, **params))
            elif type(params) == list:
                await self.send(make_notif(meth, *params))
            else:
                await self.send(make_notif(meth))
        except Exception as e:
            err_("Failed to send Notification:", e)
            if nohandle:
                raise e

    async def request(
        self,
        meth: str,
        params: Union[dict, list] = None,
        *,
        callback=None,
        nohandle=False
    ) -> Future:
        """Assemble a JSON-RPC Request with the given data. Send the Request,
            and return a Future to represent the eventual result.
        """
        echo("send", "Sending a '{}' Request to {}.".format(meth, self))
        self.total_sent["request"] += 1

        if type(params) == dict:
            data, mid = make_request(meth, **params)
        elif type(params) == list:
            data, mid = make_request(meth, *params)
        else:
            data, mid = make_request(meth)

        # Create a Future which will represent the Response.
        future: Future = self.eventloop.create_future()
        self.futures[mid] = future

        if callback:
            cb = partial(callback, remote=self)
            future.add_done_callback(cb)

        try:
            await self.send(data)
        except Exception as e:
            err_("Failed to send Request:", e)
            if nohandle:
                raise e
        finally:
            return future

    async def request_wait(
        self,
        meth: str,
        params: Union[dict, list] = None,
        default=None,
        *,
        callback=None,
        nohandle=False,
        timeout=10,
        raise_remote_err=False
    ):
        """Send a JSON-RPC Request with the given data, the same as
            `Remote.request()`. However, rather than return the Future, handle
            it, and return None if the request timed out or (unless specified)
            yielded an Error Response.
        """
        future = await self.request(meth, params, callback=callback, nohandle=nohandle)
        try:
            if timeout > 0:
                await wait_for(future, timeout)
            else:
                await future

        except RemoteError as e:
            if raise_remote_err:
                raise e
            else:
                return default
        except (TimeoutError, CancelledError):
            warn("{} Request timed out.".format(meth))
            return default

        else:
            return future.result()

    async def respond(
        self,
        mid: str,
        method: str = None,
        *,
        err: dict = None,
        res: Union[dict, list] = None,
        nohandle=False
    ):
        echo(
            "send",
            "Sending {}{} to {}.".format(
                "an Error Response" if err else "a Result Response",
                " for '{}'".format(method) if method else "",
                self,
            ),
        )
        self.total_sent["response"] += 1
        try:
            await self.send(
                make_response(mid, err=err) if err else make_response(mid, res=res)
            )
        except Exception as e:
            err_("Failed to send Response:", e)
            if nohandle:
                raise e

    async def send(self, data: str):
        await self.connection.write(data)

    async def terminate(self, reason: str = None):
        try:
            await self.notif("TERM", {"reason": reason}, nohandle=True)
        except Exception as e:
            err_("Failed to send TERM:", e)
        finally:
            self.close()
