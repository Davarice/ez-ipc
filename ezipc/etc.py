import asyncio


async def nextline(r: asyncio.StreamReader, until=b"\n"):
    line: bytes = await r.readuntil(until)
    if line == b"":
        raise ConnectionResetError("Stream closed by remote host.")
    elif line[-1] != ord(until):
        raise EOFError("Line ended early.")
    else:
        return line


class ConnectionKill(Exception):
    pass
