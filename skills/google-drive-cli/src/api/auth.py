"""One login for everything: OAuth installed-app flow (PKCE), token kept in rclone.conf.

The token lives in the rclone remote section (client_id, client_secret, token JSON) so the rclone
mount and gdrive's own Docs/Sheets calls share it; whoever refreshes first writes it back.
Credentials never travel in argv: the client comes from config/env, the redirect URL from stdin."""
import base64
import configparser
import hashlib
import json
import re
import secrets
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

from ..core import config, http, paths, profile
from ..core.errors import CliError, UsageError
from . import rclone

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/drive openid email"  # openid/email: id_token tells Workspace (hd) from gmail
PORT = 53682
REDIRECT = f"http://127.0.0.1:{PORT}/"
PENDING_TTL = 24 * 3600  # local PKCE verifier; only Google's code (after consent) lives ~10 min
WAIT_SECONDS = 600  # interactive `login` waits this long for the redirect


def _pending_path():
    return profile.dir() / "login-pending.json"


def pending_url(client_id):
    """The consent URL of a login started < 24 h ago with this client, else None. Reused so a
    rerun (onboard prints the URL each time) does not invalidate the URL the user already has."""
    p = _pending_path()
    try:
        pend = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if pend.get("client_id") == client_id and time.time() - pend.get("created", 0) < PENDING_TTL - 60:
        return pend.get("url")
    return None


def start(cfg, client_id, reuse=False):
    """New PKCE login: remember verifier+state, return the consent URL."""
    if reuse:
        url = pending_url(client_id)
        if url:
            return url
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    q = {"client_id": client_id, "redirect_uri": REDIRECT, "response_type": "code", "scope": SCOPE,
         "access_type": "offline", "prompt": "consent", "state": state,
         "code_challenge": challenge, "code_challenge_method": "S256"}
    url = AUTH_URL + "?" + urllib.parse.urlencode(q)
    paths.write_private(_pending_path(), json.dumps({"verifier": verifier, "state": state, "created": time.time(),
                                                     "remote": cfg["remote"], "client_id": client_id, "url": url}))
    return url


def parse_redirect(text):
    """The pasted redirect URL (or bare code) -> (code, state|None)."""
    text = (text or "").strip()
    if not text:
        raise UsageError("empty input: paste the full http://127.0.0.1:53682/?code=... URL from the browser")
    if "?" not in text and "=" not in text:
        return text, None
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(text).query or text.split("?", 1)[-1])
    if "error" in q:
        raise CliError(f"Google refused the consent: {q['error'][0]}")
    if "code" not in q:
        raise UsageError("no code= in the pasted URL; copy the whole address bar after consenting")
    return q["code"][0], q.get("state", [None])[0]


def finish(cfg, client_id, client_secret, code, state):
    p = _pending_path()
    if not p.exists():
        raise UsageError("no login in progress: run `gdrive login --start` (or plain `gdrive login`) first")
    pending = json.loads(p.read_text(encoding="utf-8"))
    if time.time() - pending["created"] > PENDING_TTL:
        raise UsageError("the login URL expired (24 h): start again with `gdrive login --start`")
    if state is not None and state != pending["state"]:
        raise UsageError("this redirect URL belongs to another login attempt: use the URL from the latest --start")
    try:
        tok = http.request("POST", TOKEN_URL, allow_mutate=True, retries=1, form={
            "code": code, "client_id": client_id, "client_secret": client_secret, "redirect_uri": REDIRECT,
            "grant_type": "authorization_code", "code_verifier": pending["verifier"]})
    except CliError as e:
        err = e.body.get("error") if isinstance(e.body, dict) else None
        if err in ("invalid_client", "unauthorized_client"):
            raise UsageError(f"Google rejected the OAuth client ({err}): re-import the Desktop app client JSON "
                             "with `gdrive onboard --client-file PATH`") from None
        if err == "invalid_grant":
            raise UsageError("that code was already used or expired: start the login again") from None
        raise
    if not isinstance(tok, dict) or not tok.get("refresh_token"):
        raise CliError("Google returned no refresh_token; revoke gdrive at myaccount.google.com/permissions and log in again")
    save_token(cfg["remote"], client_id, client_secret, _rclone_token(tok))
    p.unlink(missing_ok=True)
    acct = account_of(tok)
    config.update(account=acct)
    return acct


def account_of(tok):
    """Token response -> {email, domain, refresh_expires_in}. domain = the id_token 'hd' claim,
    present only for Google Workspace accounts. refresh_token_expires_in is sent when the refresh
    token is time-limited (an External app left in 'Testing': 7 days)."""
    claims = {}
    parts = (tok.get("id_token") or "").split(".")
    if len(parts) == 3:
        try:
            claims = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
        except ValueError:
            claims = {}
    exp = tok.get("refresh_token_expires_in")
    return {"email": claims.get("email"), "domain": claims.get("hd"),
            "refresh_expires_in": int(exp) if str(exp or "").isdigit() else None}


def _rclone_token(tok, refresh_token=None):
    expiry = datetime.now(timezone.utc) + timedelta(seconds=int(tok.get("expires_in", 3600)))
    return {"access_token": tok["access_token"], "token_type": tok.get("token_type", "Bearer"),
            "refresh_token": tok.get("refresh_token") or refresh_token, "expiry": expiry.isoformat()}


def parse_expiry(s):
    """rclone/Go RFC3339 (nanoseconds, Z or offset) -> aware datetime."""
    m = re.match(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(\.\d+)?(Z|[+-]\d\d:\d\d)?$", (s or "").strip())
    if not m:
        return datetime.fromtimestamp(0, timezone.utc)
    frac = (m.group(2) or ".0")[1:7].ljust(6, "0")
    tz = m.group(3) or "Z"
    tz = "+00:00" if tz == "Z" else tz
    return datetime.fromisoformat(f"{m.group(1)}.{frac}{tz}")


def _read_conf():
    cp = configparser.RawConfigParser()
    cp.optionxform = str
    path = rclone.conf()
    if path.exists():
        cp.read(path, encoding="utf-8")
    return cp


def save_token(remote, client_id, client_secret, token):
    cp = _read_conf()
    if not cp.has_section(remote):
        cp.add_section(remote)
    for k, v in (("type", "drive"), ("client_id", client_id), ("client_secret", client_secret),
                 ("scope", "drive"), ("token", json.dumps(token))):
        cp.set(remote, k, v)
    _write_conf(cp)


def _write_conf(cp):
    lines = []
    for sec in cp.sections():
        lines.append(f"[{sec}]")
        lines += [f"{k} = {v}" for k, v in cp.items(sec)]
        lines.append("")
    paths.write_private(rclone.conf(), "\n".join(lines))


def drop_token(remote):
    """Forget a token that cannot work (granted without the Drive scope): the next login replaces it."""
    cp = _read_conf()
    if cp.has_section(remote) and cp.has_option(remote, "token"):
        cp.remove_option(remote, "token")
        _write_conf(cp)


def section(remote):
    cp = _read_conf()
    if not cp.has_section(remote) or not cp.has_option(remote, "token"):
        raise UsageError(f"not logged in (no token for remote {remote!r} in {rclone.conf()}): run `gdrive login`")
    return dict(cp.items(remote))


def logged_in(remote):
    try:
        section(remote)
        return True
    except UsageError:
        return False


def access_token(remote):
    """A valid access token, refreshed (and written back for rclone) when within 60 s of expiry."""
    sec = section(remote)
    tok = json.loads(sec["token"])
    if parse_expiry(tok.get("expiry")) > datetime.now(timezone.utc) + timedelta(seconds=60):
        return tok["access_token"]
    if not tok.get("refresh_token"):
        raise UsageError("the stored token has no refresh_token: run `gdrive login` again")
    try:
        new = http.request("POST", TOKEN_URL, allow_mutate=True, retries=2, form={
            "client_id": sec.get("client_id"), "client_secret": sec.get("client_secret"),
            "refresh_token": tok["refresh_token"], "grant_type": "refresh_token"})
    except CliError as e:
        if e.status in (400, 401):  # invalid_grant: revoked, or 7-day expiry of a 'Testing' app
            raise UsageError(f"token refresh refused ({e}): run `gdrive login` again") from None
        raise
    fresh = _rclone_token(new, tok["refresh_token"])
    save_token(remote, sec.get("client_id"), sec.get("client_secret"), fresh)
    return fresh["access_token"]


def wait_redirect(timeout, prompt):
    """Interactive login: whichever comes first - the browser hitting 127.0.0.1:53682 on this
    machine, or the user pasting the redirect URL at the prompt (headless / remote browser)."""
    import http.server
    import queue
    import threading

    got = queue.Queue()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            got.put(f"{REDIRECT.rstrip('/')}{self.path}")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"gdrive: login received, you can close this tab.\n")

        def log_message(self, *a):
            pass

    server = None
    try:
        server = http.server.HTTPServer(("127.0.0.1", PORT), Handler)
        threading.Thread(target=server.handle_request, daemon=True).start()
    except OSError:
        server = None  # port busy: paste-only

    def read_stdin():
        try:
            got.put(input(prompt))
        except EOFError:
            pass

    threading.Thread(target=read_stdin, daemon=True).start()
    try:
        return got.get(timeout=timeout)
    except queue.Empty:
        return None
    finally:
        if server:
            server.server_close()


def require_remote(remote):
    """The rclone remote exists and (for Drive) holds a token. Non-drive remotes (a local alias
    used in tests) pass as-is."""
    cp = _read_conf()
    if not cp.has_section(remote):
        raise UsageError(f"not logged in (no remote {remote!r} in {rclone.conf()}): run `gdrive login`")
    if cp.get(remote, "type", fallback="") == "drive" and not cp.has_option(remote, "token"):
        raise UsageError(f"not logged in (remote {remote!r} has no token): run `gdrive login`")
