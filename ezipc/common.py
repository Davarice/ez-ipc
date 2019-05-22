"""Module defining a superclass with methods common to Clients and Servers."""

import asyncio
from datetime import datetime as dt
from . import protocol
from typing import Tuple
from uuid import UUID

from .etc import nextline


class Tunnel:
    def __init__(self, instr, outstr, group: set = None):
        self.instr = instr
        self.outstr = outstr
        self.addr, self.port = self.outstr.get_extra_info("peername", ("0.0.0.0", 0))

        self.active = []  # TODO: Give Tunnel its own EventLoop.
        self.hooks_notif = {}  # {"method": function()}
        self.hooks_request = {}  # {"method": function()}

        self.need_response = {}  # {"uuid": function()}
        self.unhandled = {}  # {"uuid": {data}}

        self.group = group

    @property
    def host(self):
        return ":".join((self.addr, str(self.port)))

    async def get_data(self):
        try:
            data = protocol.unpack(await nextline(self.instr))
        except IndexError:
            raise ConnectionResetError("Stream Ended.")
        await asyncio.sleep(0.1)  # Allow a moment to finalize.

        if "error" in data or "result" in data:
            # Message is a RESPONSE.
            mid = data["id"]
            if mid in self.need_response:
                # Something is waiting for this message.
                func = self.need_response[mid]
                del self.need_response[mid]
                self.active.append(await asyncio.create_task(func(data)))
            else:
                # Nothing is waiting for this message...Save it anyway.
                self.unhandled[mid] = data
        elif "id" in data:
            # Message is a REQUEST.
            if data["method"] in self.hooks_request:
                # We know where to send this type of Request.
                func = self.hooks_request[data["method"]]
                self.active.append(await asyncio.create_task(func(data)))
            else:
                # We have no hook for this method; Return an Error.
                await self.send(
                    protocol.response(
                        data["id"],
                        err=protocol.Errors.method_not_found(data.get("method")),
                    )
                )
        else:
            # Message is a NOTIFICATION.
            if data["method"] in self.hooks_notif:
                # We know where to send this type of Notification.
                func = self.hooks_notif[data["method"]]
                self.active.append(await asyncio.create_task(func(data)))

    def hook_response(self, uuid: str, func):
        """Signal to the Tunnel that `func` is waiting for a Response with an ID
            field of `uuid`.
        """
        self.need_response[uuid] = func

    async def loop(self):
        try:
            while True:
                await self.get_data()

        except EOFError:
            print("Connection with {} hit EOF.".format(self.host))
        except ConnectionError as e:
            print("Connection with {} closed: {}".format(self.host, e))
        finally:
            self.outstr.close()
            if self.group is not None and self in self.group:
                self.group.remove(self)

    async def notif(self, meth: str, params=None):
        """Assemble and send a JSON-RPC Notification with the given data."""
        if type(params) == dict:
            await self.send(protocol.notif(meth, **params))
        elif type(params) == list:
            await self.send(protocol.notif(meth, *params))
        else:
            await self.send(protocol.notif(meth))

    async def request(self, meth: str, params=None) -> Tuple[UUID, dt]:
        """Assemble a JSON-RPC Request with the given data. Send the Request,
            and return the UUID and timestamp of the message, so that we can
            find the Response.
        """
        if type(params) == dict:
            data, mid = protocol.request(meth, **params)
        elif type(params) == list:
            data, mid = protocol.request(meth, *params)
        else:
            data, mid = protocol.request(meth)
        await self.send(data)
        return UUID(hex=mid), dt.utcnow()

    async def send(self, data: bytes):
        self.outstr.write(data if data[-1] == 10 else data + b"\n")
        await self.outstr.drain()
