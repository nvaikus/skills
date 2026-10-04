"""User-facing failures. The CLI prints them as `error: ...` (exit 2); the web
API maps them to 400 / 404 / 409 — one wording for both."""


class UserError(Exception):
    status = 400

    def __init__(self, msg, where=""):
        super().__init__(msg)
        self.msg = msg
        self.where = where  # "file.yaml:3" — the CLI shows it, a web form has no lines

    def __str__(self):
        return f"{self.where}: {self.msg}" if self.where else self.msg


class ValidationError(UserError):
    status = 400


class NotFound(UserError):
    status = 404


class Conflict(UserError):
    status = 409
