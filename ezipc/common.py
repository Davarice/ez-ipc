"""Module defining a superclass with methods common to Clients and Servers."""

import asyncio
from datetime import datetime as dt
from json import JSONDecodeError
from typing import Tuple
from uuid import UUID, uuid4

from . import protocol
from .etc import nextline


class Tunnel:
    def __init__(self, instr, outstr, group: set = None):
        self.instr = instr
        self.outstr = outstr
        self.addr, self.port = self.outstr.get_extra_info("peername", ("0.0.0.0", 0))

        self.active = []
        self.hooks_notif = {}  # {"method": function()}
        self.hooks_request = {}  # {"method": function()}

        self.need_response = {}  # {"uuid": function()}
        self.unhandled = {}  # {"uuid": {data}}

        self.group = group
        self.id = hex(
            (uuid4().int + self.port + sum([int(s) for s in self.addr.split(".")]))
            % 16 ** 5
        )[2:]

    @property
    def host(self):
        return "{}:{}".format(self.addr, self.port)

    async def get_data(self):
        try:
            data = protocol.unpack(await nextline(self.instr))
        except JSONDecodeError as e:
            print("--> Invalid JSON received from Remote {}".format(self.id))
            await self.send(
                protocol.response("0", err=protocol.Errors.parse_error(str(e)))
            )
            return

        await asyncio.sleep(0.2)  # Allow a moment to finalize.

        keys = list(data.keys())
        # if "error" in data or "result" in data:
        if protocol.verify_response(keys, data):
            # Message is a RESPONSE.
            print("--> Receiving a Response from Remote {}".format(self.id))
            mid = data["id"]
            if mid in self.need_response:
                # Something is waiting for this message.
                func = self.need_response[mid]
                del self.need_response[mid]
                self.active.append(await asyncio.create_task(func(data, self)))
            else:
                # Nothing is waiting for this message...Save it anyway.
                self.unhandled[mid] = data
        # elif "id" in data:
        elif protocol.verify_request(keys, data):
            # Message is a REQUEST.
            print(
                "--> Receiving a '{}' Request from Remote {}".format(data["method"], self.id)
            )
            if data["method"] in self.hooks_request:
                # We know where to send this type of Request.
                func = self.hooks_request[data["method"]]
                # await func(data, self)
                tsk = await asyncio.create_task(func(data, self))
                self.active.append(tsk)
            else:
                # We have no hook for this method; Return an Error.
                await self.send(
                    protocol.response(
                        data["id"],
                        err=protocol.Errors.method_not_found(data.get("method")),
                    )
                )
        # else:
        elif protocol.verify_notif(keys, data):
            # Message is a NOTIFICATION.
            print(
                "--> Receiving a '{}' Notification from Remote {}".format(
                    data["method"], self.id
                )
            )
            if data["method"] == "TERM":
                # The connection is being explicitly terminated.
                raise ConnectionResetError("Connection terminated by peer.")
            elif data["method"] in self.hooks_notif:
                # We know where to send this type of Notification.
                func = self.hooks_notif[data["method"]]
                self.active.append(await asyncio.create_task(func(data, self)))
        else:
            # Message is not a valid JSON-RPC structure. If we can find an ID,
            #   send a Response containing an Error and a frowny face.
            print("Received an invalid Request from Remote {}".format(self.id))
            if "id" in data:
                await self.send(
                    protocol.response(
                        data["id"],
                        err=protocol.Errors.invalid_request(list(data.keys())),
                    )
                )

    def hook_notif(self, method: str, func):
        """Signal to the Tunnel that `func` is waiting for Notifications of the
            provided `method` value.
        """
        self.hooks_notif[method] = func

    def hook_request(self, method: str, func):
        """Signal to the Tunnel that `func` is waiting for Requests of the
            provided `method` value.
        """
        self.hooks_request[method] = func

    def hook_response(self, uuid: str, func):
        """Signal to the Tunnel that `func` is waiting for a Response with an ID
            field of `uuid`.
        """
        self.need_response[uuid] = func

    async def close(self):
        for coro in self.active:
            # Cancel all running Tasks.
            if coro:
                coro.cancel()
        if self.group is not None and self in self.group:
            # Remove self from Client Set, if possible.
            self.group.remove(self)
        if self.outstr.can_write_eof():
            # Send an EOF, if possible.
            self.outstr.write_eof()
            # await self.outstr.drain()
        # Finally, close the Stream.
        self.outstr.close()

    async def loop(self):
        try:
            while True:
                await self.get_data()
        except EOFError:
            print("X   Connection with {} hit EOF.".format(self.id))
            await self.close()
        except ConnectionError as e:
            print("X   Connection with {} closed: {}".format(self.id, e))
            await self.close()
        except asyncio.CancelledError:
            print("Listening to {} was cancelled.".format(self.id))

    async def notif(self, meth: str, params=None):
        """Assemble and send a JSON-RPC Notification with the given data."""
        print("<-- Sending a '{}' Notification to Remote {}.".format(meth, self.id))
        if type(params) == dict:
            await self.send(protocol.notif(meth, **params))
        elif type(params) == list:
            await self.send(protocol.notif(meth, *params))
        else:
            await self.send(protocol.notif(meth))

    async def request(self, meth: str, params=None, callback=None) -> Tuple[UUID, dt]:
        """Assemble a JSON-RPC Request with the given data. Send the Request,
            and return the UUID and timestamp of the message, so that we can
            find the Response.
        """
        print("<-- Sending a '{}' Request to Remote {}.".format(meth, self.id))
        if type(params) == dict:
            data, mid = protocol.request(meth, **params)
        elif type(params) == list:
            data, mid = protocol.request(meth, *params)
        else:
            data, mid = protocol.request(meth)
        await self.send(data)

        if callback:
            self.hook_response(mid, callback)

        return UUID(hex=mid), dt.utcnow()

    async def respond(self, mid: str, *, err=None, res=None):
        print(
            "<-- Sending a {} Response to Remote {}.".format(
                "Failure" if err else "Success", self.id
            )
        )
        await self.send(
            protocol.response(mid, err=err) if err else protocol.response(mid, res=res)
        )

    async def send(self, data: bytes):
        self.outstr.write(data if data[-1] == 10 else data + b"\n")
        await self.outstr.drain()

    async def terminate(self):
        await self.notif("TERM")
        await self.close()
