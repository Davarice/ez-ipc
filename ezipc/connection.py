from asyncio import StreamReader, StreamWriter

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
    def __init__(self, instr: StreamReader, outstr: StreamWriter):
        self.instr: StreamReader = instr
        self.outstr: StreamWriter = outstr

        self.can_encrypt = can_encrypt

        self._key: PrivateKey = PrivateKey.generate() if self.can_encrypt else None
        self.key_other: PublicKey = None
        self._box: Box = None
        self.box: Box = None

    @property
    def key(self):
        return bytes(self._key.public_key).hex() if self.can_encrypt else None

    def add_key(self, pubkey: str):
        if pubkey and self.can_encrypt:
            self.key_other = PublicKey(bytes.fromhex(pubkey))
            self._box = Box(self._key, self.key_other)

    def begin_encryption(self):
        self.box = self._box

    def can_activate(self):
        return bool(self._box and not self.box)

    def _decrypt(self, data):
        if self.box:
            return self.box.decrypt(data)
        else:
            return data

    def _encrypt(self, data):
        if self.box:
            return self.box.encrypt(data)
        else:
            return data

    async def readline(self):
        data = self.instr.readline()
        return self._decrypt(data)

    async def readuntil(self, *a, **kw):
        data = self.instr.readuntil(*a, **kw)
        return self._decrypt(data)

    async def read(self, *a, **kw):
        data = self.instr.read(*a, **kw)
        return self._decrypt(data)

    async def write(self, data: bytes):
        self.outstr.write(data)
        self.outstr.write(b"\n")
        await self.outstr.drain()
