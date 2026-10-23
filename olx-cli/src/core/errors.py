"""The only user-visible failures. Exit codes are contract (see top --help)."""


class CliError(Exception):
    """exit 1: OLX/network/runtime failure. payload: row dicts printed on stderr under the message."""
    code = 1

    def __init__(self, msg, code=None, payload=None, status=None, body=None):
        super().__init__(msg)
        if code is not None:
            self.code = code
        self.payload = payload
        self.status = status  # HTTP status, when the failure came from a response
        self.body = body


class UsageError(CliError):
    """exit 2: usage, config, unknown name, listing not found."""
    code = 2


class Broken(CliError):
    """exit 3: OLX refused the client (403/captcha/HTML instead of JSON) or the JSON shape changed.
    The unofficial endpoint 'broke': see references/traps.md 'When it breaks'."""
    code = 3
