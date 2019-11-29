from asyncio import StreamReader, StreamWriter
from typing import List, Optional, Union

try:
    # noinspection PyPackageRequirements
    from nacl.encoding import HexEncoder

    # noinspection PyPackageRequirements
    from nacl.exceptions import CryptoError

    # noinspection PyPackageRequirements
    from nacl.public import Box, PrivateKey, PublicKey

    # noinspection PyPackageRequirements
    from nacl.signing import SigningKey, VerifyKey

except ImportError as ex:
    HexEncoder = None

    class CryptoError(Exception):
        pass

    Box = None
    PrivateKey = None
    PublicKey = None

    SigningKey = None
    VerifyKey = None

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
        "_key_priv",
        "_key_sign",
        "key_other_pub",
        "key_other_ver",
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

        self._key_priv: PrivateKey = PrivateKey.generate() if self.can_encrypt else None
        self._key_sign: SigningKey = SigningKey.generate() if self.can_encrypt else None

        self.key_other_pub: PublicKey = None
        self.key_other_ver: VerifyKey = None

        self._box: Box = None
        self.box: Box = None

        self.total_sent: int = 0
        self.total_recv: int = 0

    @property
    def encrypted(self) -> bool:
        return bool(self.box)

    @property
    def keys(self) -> Optional[List[str]]:
        return (
            [
                self._key_priv.public_key.encode(HexEncoder).decode(),
                self._key_sign.verify_key.encode(HexEncoder).decode(),
            ]
            if self.can_encrypt
            else None
        )

    def _decrypt(self, ctext: bytes) -> bytes:
        if self.encrypted:
            ptext = self.box.decrypt(ctext)
            if self.key_other_ver:
                return self.key_other_ver.verify(ptext)
            else:
                return ptext
        else:
            return ctext

    def _encrypt(self, ptext: bytes) -> bytes:
        if self.encrypted:
            if self._key_sign:
                ptext = self._key_sign.sign(ptext)

            return self.box.encrypt(ptext)
        else:
            return ptext

    def add_keys(self, pubkey: str, verkey: str) -> None:
        if pubkey and verkey and self.can_encrypt:
            self.key_other_pub = PublicKey(pubkey.encode(), HexEncoder)
            self.key_other_ver = VerifyKey(verkey.encode(), HexEncoder)

            self._box = Box(self._key_priv, self.key_other_pub)

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
