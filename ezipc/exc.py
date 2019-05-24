"""Module providing EZ-IPC Exceptions."""


class EZError(Exception):
    """Generic Error. Catches all custom Exceptions of the Package."""


class RemoteError(EZError):
    """Error sent by the Remote Host over JSON-RPC. May contain extra data."""

    data = property(lambda self: object(), lambda self, v: None, lambda self: None)
