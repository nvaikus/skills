"""The only user-visible failures. Exit codes are contract (see top --help)."""


class CliError(Exception):
    """exit 1: eBay or runtime failure. payload: row dicts printed on stderr under the message."""
    code = 1

    def __init__(self, msg, code=None, payload=None, status=None, body=None):
        super().__init__(msg)
        if code is not None:
            self.code = code
        self.payload = payload
        self.status = status  # HTTP status, when the failure came from a response
        self.body = body


class UsageError(CliError):
    """exit 2: usage, config, no keys, item not found."""
    code = 2


class Waiting(CliError):
    """exit 5: setup waits on the user (relay the step, rerun)."""
    code = 5
