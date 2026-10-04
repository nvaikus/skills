"""Authorized Google REST calls (Drive v3, Docs v1, Sheets v4). The only api/ helper that mutates."""
from ..core import http
from ..core.errors import CliError, UsageError
from . import auth

DRIVE = "https://www.googleapis.com/drive/v3"
DOCS = "https://docs.googleapis.com/v1"
SHEETS = "https://sheets.googleapis.com/v4"


def _call(remote, method, url, params=None, body=None, allow_mutate=False):
    hdrs = {"Authorization": f"Bearer {auth.access_token(remote)}"}
    try:
        return http.request(method, url, params=params, body=body, headers=hdrs, allow_mutate=allow_mutate)
    except CliError as e:
        raise translate(e) from None


def translate(e):
    """Google error -> the exit code a caller must act on. Never branch on message text elsewhere."""
    body = e.body if isinstance(e.body, dict) else {}
    err = body.get("error") if isinstance(body.get("error"), dict) else {}
    reasons = {d.get("reason") for d in err.get("errors", []) if isinstance(d, dict)}
    reasons |= {d.get("reason") for d in err.get("details", []) if isinstance(d, dict)}
    msg = err.get("message") or str(e)
    kw = {"status": e.status, "body": e.body}  # callers classify by status/reason, never by text
    if e.status == 401:
        return UsageError(f"Google rejected the token ({msg}): run `gdrive login` again", **kw)
    if e.status == 403 and {"accessNotConfigured", "SERVICE_DISABLED"} & reasons:
        return UsageError(f"{msg}\n(enable that API in the Google Cloud project of your OAuth client, then retry)", **kw)
    if e.status == 403 and {"insufficientPermissions", "ACCESS_TOKEN_SCOPE_INSUFFICIENT"} & reasons:
        return UsageError(f"{msg}\n(the token lacks the drive scope: run `gdrive login` again)", **kw)
    if e.status == 403 and ({"insufficientFilePermissions", "cannotAddChildren"} & reasons
                            or err.get("status") == "PERMISSION_DENIED"):
        return UsageError(f"{msg}\n(this account may not change it: an item shared with view/comment access, or a "
                          "folder you cannot add to; ask the owner for edit access, or copy it into My Drive)", **kw)
    if e.status == 404:
        return UsageError(f"not found: {msg}", **kw)
    return CliError(f"Google API error {e.status}: {msg}", **kw)


def reasons(e):
    """Google error reasons of a CliError (errors[].reason + details[].reason)."""
    body = e.body if isinstance(e.body, dict) else {}
    err = body.get("error") if isinstance(body.get("error"), dict) else {}
    return {d.get("reason") for d in err.get("errors", []) + err.get("details", []) if isinstance(d, dict)}


def download(remote, url, dest, params=None):
    """Authorized GET of a file body (alt=media / export) into dest - never through a mount."""
    try:
        http.download(url, dest, timeout=300, headers={"Authorization": f"Bearer {auth.access_token(remote)}"},
                      params=params)
    except CliError as e:
        raise translate(e) from None


def get(remote, url, params=None):
    return _call(remote, "GET", url, params=params)


def mutate(remote, method, url, body=None, params=None):
    """Every write to Google goes through here (grep target for audits)."""
    return _call(remote, method, url, params=params, body=body, allow_mutate=True)
