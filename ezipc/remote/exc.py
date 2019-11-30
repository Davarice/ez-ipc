"""Module providing EZ-IPC Exceptions."""

from typing import Optional


class EZError(Exception):
    """Generic Error. Catches all custom Exceptions of the Package."""


class RemoteError(EZError):
    """Error sent by the Remote Host over JSON-RPC. May contain extra data.

    Should always be given four arguments:
        - Error code received from Server
        - Message attached to Error
        - REPR of the data included in the Message
        - UUID of the Response (and, by extension, original) Message
    """

    @classmethod
    def from_message(cls, data: dict) -> Optional["RemoteError"]:
        errdat = data.get("error")
        if not errdat:
            return None
        else:
            # No KeyError handling here because trying to do this should really
            #   return one anyway.
            return cls(errdat["code"], errdat["message"], errdat["data"], data["id"])

    @property
    def code(self):
        return self.args[0]

    @property
    def message(self):
        return self.args[1]

    @property
    def data(self):
        return self.args[2]

    @property
    def id(self):
        return self.args[3]

    def __str__(self):
        # return "Error {}: {}: {} (ID: {})".format(
        #     self.code, self.message, repr(self.data), self.id
        # )
        return f"Error {self.code!r}: {self.message}"
