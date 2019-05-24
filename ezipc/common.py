"""Module defining a superclass with methods common to Clients and Servers."""

import asyncio
from datetime import datetime as dt
from functools import partial
from json import JSONDecodeError
from typing import Union
from uuid import uuid4

from . import protocol
from .exc import RemoteError
from .output import echo, err as err_, warn


class Remote:
    def __init__(self, eventloop, instr, outstr, group: set = None):
        self.eventloop: asyncio.AbstractEventLoop = eventloop
        self.instr = instr
        self.outstr = outstr
        self.addr, self.port = self.outstr.get_extra_info("peername", ("0.0.0.0", 0))

        self.active = []
        self.hooks_notif = {}  # {"method": function()}
        self.hooks_request = {}  # {"method": function()}

        self.futures = {}  # {"uuid": function()}

        self.group = group
        self.id = hex(
            (uuid4().int + self.port + sum([int(s) for s in self.addr.split(".")]))
            % 16 ** 5
        )[2:]

        now = dt.utcnow()
        self.opened = now
        self.startup = now

    @property
    def host(self):
        return "{}:{}".format(self.addr, self.port)

    def __str__(self):
        return "Remote " + self.id

    async def get_line(self, until=b"\n"):
        line: bytes = await self.instr.readuntil(until)
        if line == b"":
            raise ConnectionResetError("Stream closed by remote host.")
        elif line[-1] != ord(until):
            raise EOFError("Line ended early.")
        else:
            return line

    async def process_line(self, line):
        try:
            data = protocol.unpack(line)
        except JSONDecodeError as e:
            echo("recv", "Invalid JSON received from {}".format(self))
            await self.send(
                protocol.make_response("0", err=protocol.Errors.parse_error(str(e)))
            )
            return

        await asyncio.sleep(0.2)  # Allow a moment to finalize.

        keys = list(data.keys())
        if protocol.verify_response(keys, data):
            # Message is a RESPONSE.
            echo("recv", "Receiving a Response from {}".format(self))
            mid = data["id"]
            if mid in self.futures:
                # Something is waiting for this message.
                future: asyncio.Future = self.futures[mid]
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
                        eline = "Error {}: {}".format(data["error"]["code"], data["error"]["message"])
                        e = RemoteError(eline, data["error"]["data"] if "data" in data["error"] else None, mid)
                        future.set_exception(e)
                    else:
                        # Server sent a Result Response. Give it to the Future.
                        future.set_result(data["result"])
            else:
                # Nothing is waiting for this message. Make a note and move on.
                warn("Received an unsolicited Response. UUID: {}".format(mid))

        elif protocol.verify_request(keys, data):
            # Message is a REQUEST.
            echo(
                "recv", "Receiving a '{}' Request from {}".format(data["method"], self)
            )
            if data["method"] in self.hooks_request:
                # We know where to send this type of Request.
                func = self.hooks_request[data["method"]]
                # await func(data, self)
                tsk = asyncio.ensure_future(func(data, self))
                self.active.append(tsk)
            else:
                # We have no hook for this method; Return an Error.
                await self.send(
                    protocol.make_response(
                        data["id"],
                        err=protocol.Errors.method_not_found(data.get("method")),
                    )
                )

        elif protocol.verify_notif(keys, data):
            # Message is a NOTIFICATION.
            echo(
                "recv",
                "Receiving a '{}' Notification from {}".format(data["method"], self),
            )
            if data["method"] == "TERM":
                # The connection is being explicitly terminated.
                raise ConnectionResetError(data["params"]["reason"] or "Connection terminated by peer.")
            elif data["method"] in self.hooks_notif:
                # We know where to send this type of Notification.
                func = self.hooks_notif[data["method"]]
                self.active.append(asyncio.ensure_future(func(data, self)))

        else:
            # Message is not a valid JSON-RPC structure. If we can find an ID,
            #   send a Response containing an Error and a frowny face.
            echo("", "Received an invalid Request from {}".format(self))
            if "id" in data:
                await self.send(
                    protocol.make_response(
                        data["id"],
                        err=protocol.Errors.invalid_request(list(data.keys())),
                    )
                )

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

    def hook_response(self, uuid: str, func):
        """Signal to the Remote that `func` is waiting for a Response with an ID
            field of `uuid`.
        """
        self.futures[uuid] = func

    def close(self):
        for coro in self.active:
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
                await self.process_line(await self.get_line())
                tasks = asyncio.gather(*self.active)
                self.active = []
                await tasks
        except asyncio.IncompleteReadError:
            err_("Connection with {} cut off.".format(self))
        except EOFError:
            err_("Connection with {} failed: Stream ended.".format(self))
            self.close()
        except ConnectionError as e:
            err_("Connection with {} closed:".format(self), e)
            self.close()
        except asyncio.CancelledError:
            err_("Listening to {} was cancelled.".format(self))
        except Exception as e:
            err_("Connection with {} failed:".format(self), e)

    async def notif(self, meth: str, params=None, nohandle=False):
        """Assemble and send a JSON-RPC Notification with the given data."""
        try:
            echo("send", "Sending a '{}' Notification to {}.".format(meth, self))
            if type(params) == dict:
                await self.send(protocol.make_notif(meth, **params))
            elif type(params) == list:
                await self.send(protocol.make_notif(meth, *params))
            else:
                await self.send(protocol.make_notif(meth))
        except Exception as e:
            if nohandle:
                raise e
            err_("Failed to send Notification:", e)

    async def request(
        self, meth: str, params: Union[dict, list] = None, callback=None, nohandle=False
    ) -> asyncio.Future:
        """Assemble a JSON-RPC Request with the given data. Send the Request,
            and return a Future to represent the eventual result.
        """
        echo("send", "Sending a '{}' Request to {}.".format(meth, self))

        if type(params) == dict:
            data, mid = protocol.make_request(meth, **params)
        elif type(params) == list:
            data, mid = protocol.make_request(meth, *params)
        else:
            data, mid = protocol.make_request(meth)

        # Create a Future which will represent the Response.
        future: asyncio.Future = self.eventloop.create_future()
        self.hook_response(mid, future)

        if callback:
            cb = partial(callback, remote=self)
            future.add_done_callback(cb)

        try:
            await self.send(data)
        except Exception as e:
            if nohandle:
                raise e
            err_("Failed to send Request:", e)
        finally:
            return future

    async def respond(self, mid: str, method=None, *, err=None, res=None, nohandle=False):
        echo(
            "send",
            "Sending {}{} to {}.".format(
                "an Error Response" if err else "a Result Response",
                " for '{}'".format(method) if method else "",
                self
            ),
        )
        try:
            await self.send(
                protocol.make_response(mid, err=err)
                if err
                else protocol.make_response(mid, res=res)
            )
        except Exception as e:
            if nohandle:
                raise e
            err_("Failed to send Response:", e)

    async def send(self, data: bytes):
        self.outstr.write(data if data[-1] == 10 else data + b"\n")
        await self.outstr.drain()

    async def terminate(self, reason: str = None):
        try:
            await self.notif("TERM", {"reason": reason}, nohandle=True)
        except Exception as e:
            err_("Failed to send TERM:", e)
        finally:
            self.close()