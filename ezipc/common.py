"""Module defining a superclass with methods common to Clients and Servers."""

import asyncio
from datetime import datetime as dt
import protocol
from typing import Tuple
from uuid import UUID


class Tunnel:
    def __init__(self, instr, outstr):
        self.incoming = {}
        self.instr = instr
        self.outstr = outstr

    async def get_data(self):
        pass

    async def notif(self, meth: str, params=None):
        """Assemble and send a JSON-RPC Notification with the given data."""
        if type(params) == dict:
            await self.send(protocol.notif(meth, **params))
        elif type(params) == dict:
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
        elif type(params) == dict:
            data, mid = protocol.request(meth, *params)
        else:
            data, mid = protocol.request(meth)
        await self.send(data)
        return UUID(hex=mid), dt.utcnow()

    async def send(self, data: bytes):
        self.outstr.write(data if data[-1] == 10 else data + b"\n")
        await self.outstr.drain()
