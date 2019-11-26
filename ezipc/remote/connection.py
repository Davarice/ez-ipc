from asyncio import StreamReader, StreamWriter
from typing import Optional, Union

try:
    # noinspection PyPackageRequirements
    from nacl.exceptions import CryptoError

    # noinspection PyPackageRequirements
    from nacl.public import Box, PrivateKey, PublicKey
except ImportError as ex:

    class CryptoError(Exception):
        pass

    Box = None
    PrivateKey = None
    PublicKey = None
    can_encrypt: bool = False

    print("Encryption could not be enabled:", ex)
else:
    can_encrypt: bool = True


sep: bytes = b"\n" * 5


class Connection:
    __slots__ = (
        "instr",
        "outstr",
        "encoding",
        "can_encrypt",
        "open",
        "_key",
        "key_other",
        "_box",
        "box",
        "total_sent",
        "total_recv",
    )

    def __init__(
        self, instr: StreamReader, outstr: StreamWriter, *, encoding: str = "utf-16",
    ):
        self.instr: StreamReader = instr
        self.outstr: StreamWriter = outstr
        self.encoding: str = encoding

        self.can_encrypt: bool = can_encrypt
        self.open: bool = True

        self._key: PrivateKey = PrivateKey.generate() if self.can_encrypt else None
        self.key_other: PublicKey = None
        self._box: Box = None
        self.box: Box = None

        self.total_sent: int = 0
        self.total_recv: int = 0

    @property
    def key(self) -> Optional[str]:
        return bytes(self._key.public_key).hex() if self.can_encrypt else None

    def _decrypt(self, ctext: bytes) -> bytes:
        if self.box:
            return self.box.decrypt(ctext)
        else:
            return ctext

    def _encrypt(self, ptext: bytes) -> bytes:
        if self.box:
            return self.box.encrypt(ptext)
        else:
            return ptext

    def add_key(self, pubkey: str) -> None:
        if pubkey and self.can_encrypt:
            self.key_other = PublicKey(bytes.fromhex(pubkey))
            self._box = Box(self._key, self.key_other)

    def begin_encryption(self) -> None:
        self.box = self._box

    def close(self) -> None:
        self.open = False

        if not self.outstr.is_closing():
            if self.outstr.can_write_eof():
                # Send an EOF, if possible.
                self.outstr.write_eof()

            # Close the Stream.
            self.outstr.close()

    def encryption_ready(self) -> bool:
        return bool(self._box and self._box is not self.box)

    async def read(self) -> str:
        ctext: bytes = await self.instr.readuntil(sep)
        self.total_recv += len(ctext)
        ptext: str = self._decrypt(ctext[: -len(sep)]).decode(self.encoding)
        return ptext

    async def write(self, ptext: str) -> int:
        ctext: bytes = self._encrypt(ptext.encode(self.encoding))
        self.outstr.write(ctext)
        self.outstr.write(sep)

        count = len(ctext) + len(sep)
        self.total_sent += count

        await self.outstr.drain()
        return count

    def __aiter__(self):
        return self

    async def __anext__(self) -> Union[CryptoError, str]:
        try:
            line: str = await self.read()
            if line and self.open:
                return line
            else:
                raise StopAsyncIteration
        except CryptoError as e:
            return e
