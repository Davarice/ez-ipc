import asyncio

try:
    import nacl.utils
    from nacl.public import Box, PrivateKey, PublicKey
except ImportError:
    Box = None
    PrivateKey = None
    PublicKey = None
    can_encrypt = False
else:
    can_encrypt = True


class Connection:
    def __init__(self, instr: asyncio.StreamReader, outstr: asyncio.StreamWriter):
        self.instr: asyncio.StreamReader = instr
        self.outstr: asyncio.StreamWriter = outstr

        self._key = PrivateKey.generate() if can_encrypt else None
        self.key_other = None
        self._box = None
        self.box = None

    @property
    def key(self):
        return self._key.public_key if can_encrypt else None

    def add_key(self, pubkey: bytes):
        if can_encrypt:
            self.key_other = PublicKey(pubkey)
            self._box = Box(self.key, self.key_other)

    def begin_encryption(self):
        self.box = self._box

    def decrypt(self, data):
        if self.box:
            return self.box.decrypt(data)
        else:
            return data

    def encrypt(self, data):
        if self.box:
            return self.box.encrypt(data)
        else:
            return data

    async def readline(self):
        data = self.instr.readline()
        return self.decrypt(data)

    async def readuntil(self, *a, **kw):
        data = self.instr.readuntil(*a, **kw)
        return self.decrypt(data)

    async def read(self, *a, **kw):
        data = self.instr.read(*a, **kw)
        return self.decrypt(data)

    async def write(self, data: bytes):
        self.outstr.write(self.encrypt(data))
        self.outstr.write(b"\n")
        await self.outstr.drain()
