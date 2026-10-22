class PrintError(Exception):
    """An error safe to display to a user (never include request bodies)."""


class UncertainSubmission(PrintError):
    """A server mutation may have succeeded. Do not automatically repeat it."""


class ServerRejected(PrintError):
    def __init__(self, code, endpoint, message):
        super().__init__(message)
        self.code = code
        self.endpoint = endpoint
