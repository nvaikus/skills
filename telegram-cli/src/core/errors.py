"""The only user-visible failures. Exit codes are contract (see top --help)."""


class CliError(Exception):
    """exit 1: Telegram/runtime failure. payload: rows printed on stderr under the message."""
    code = 1

    def __init__(self, msg, code=None, payload=None):
        super().__init__(msg)
        if code is not None:
            self.code = code
        self.payload = payload


class UsageError(CliError):
    """exit 2: usage, config, not logged in, target not found or ambiguous."""
    code = 2


class Refused(CliError):
    """exit 3: safety refusal, nothing was sent."""
    code = 3


class Cannot(CliError):
    """exit 4: domain 'cannot' (account lacks Premium)."""
    code = 4
