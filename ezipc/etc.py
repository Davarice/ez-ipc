import asyncio


async def nextline(r: asyncio.StreamReader, until="\n"):
    line: bytes = await r.readline()
    if line[-1] != ord(until):
        raise EOFError("Line ended early.")
    else:
        return line


class ConnectionKill(Exception):
    pass
