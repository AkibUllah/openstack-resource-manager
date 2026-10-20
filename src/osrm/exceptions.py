class OsrmError(Exception):
    """Base error with a user-facing message."""


class NotFound(OsrmError):
    def __init__(self, resource: str, identifier: str):
        super().__init__(f"{resource} {identifier!r} not found")
        self.resource = resource
        self.identifier = identifier


class BackendUnavailable(OsrmError):
    pass


class InvalidState(OsrmError):
    pass
