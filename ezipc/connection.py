import asyncio

try:
    import nacl.utils
    from nacl.public import Box, PrivateKey
except ImportError:
    Box = None
    PrivateKey = None
    can_encrypt = False
else:
    can_encrypt = True


class Connection:
    def __init__(self, instr: asyncio.StreamReader, outstr: asyncio.StreamWriter):
        self.instr: asyncio.StreamReader = instr
        self.outstr: asyncio.StreamWriter = outstr

        self.key = PrivateKey.generate() if can_encrypt else None
        self.key_other = None
        self.box = None

    def add_key(self, pkey):
        pass

    def decrypt(self, data: bytes):
        pass

    def encrypt(self, data: bytes):
        pass

    async def readline(self):
        pass

    async def readuntil(self, separator=b"\n"):
        pass

    async def read(self, n=-1):
        pass

    async def write(self, data):
        pass
