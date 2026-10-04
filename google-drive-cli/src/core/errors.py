"""The only user-visible failures. Exit codes are contract (see top --help)."""


class CliError(Exception):
    """exit 1: Google/rclone/runtime failure, or work that finished badly.
    payload: list of row dicts printed on stderr under the message (candidates, log tail)."""
    code = 1

    def __init__(self, msg, code=None, payload=None, status=None, body=None):
        super().__init__(msg)
        if code is not None:
            self.code = code
        self.payload = payload
        self.status = status  # HTTP status, when the failure came from a response
        self.body = body


class UsageError(CliError):
    """exit 2: usage, config, not logged in, target not found or ambiguous."""
    code = 2


class Refused(CliError):
    """exit 3: safety-rail refusal, nothing was changed."""
    code = 3


class Deadline(CliError):
    """exit 6: --wait deadline hit; nothing was undone, the work continues in the background."""
    code = 6
