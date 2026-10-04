"""OAuth installed-app flow (PKCE, loopback redirect) and the per-profile token file.

Every function takes the profile name: search runs several profiles in parallel threads.
Credentials never travel in argv: the client comes from config/env, the redirect URL from stdin."""
import base64
import hashlib
import json
import secrets
import threading
import time
import urllib.parse

from ..core import config, http, paths, profile
from ..core.errors import CliError, UsageError

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.modify"  # read, labels, drafts, send, trash - no permanent delete
SETTINGS_SCOPE = "https://www.googleapis.com/auth/gmail.settings.basic"  # filters; added later: old tokens lack it
SCOPE = f"{GMAIL_SCOPE} {SETTINGS_SCOPE} openid email"  # openid/email: id_token tells Workspace (hd) from gmail
PORT = 53682
REDIRECT = f"http://127.0.0.1:{PORT}/"
PENDING_TTL = 24 * 3600  # local PKCE verifier; only Google's code (after consent) lives ~10 min
WAIT_SECONDS = 600  # interactive `login` waits this long for the redirect

_lock = threading.Lock()
_cache = {}  # profile -> (access_token, expires_epoch)


def token_path(prof):
    return profile.dir(prof) / "token.json"


def _pending_path(prof):
    return profile.dir(prof) / "login-pending.json"


def pending_url(prof, client_id):
    """The consent URL of a login started < 24 h ago with this client, else None. Reused so a
    rerun (onboard prints the URL each time) does not invalidate the URL the user already has."""
    try:
        pend = json.loads(_pending_path(prof).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if pend.get("client_id") == client_id and time.time() - pend.get("created", 0) < PENDING_TTL - 60:
        return pend.get("url")
    return None


def start(prof, client_id, reuse=False, hint=None):
    """New PKCE login: remember verifier+state, return the consent URL."""
    if reuse:
        url = pending_url(prof, client_id)
        if url:
            return url
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    q = {"client_id": client_id, "redirect_uri": REDIRECT, "response_type": "code", "scope": SCOPE,
         "access_type": "offline", "prompt": "consent", "state": state,
         "code_challenge": challenge, "code_challenge_method": "S256"}
    if hint:
        q["login_hint"] = hint
    url = AUTH_URL + "?" + urllib.parse.urlencode(q)
    paths.write_private(_pending_path(prof), json.dumps({"verifier": verifier, "state": state, "created": time.time(),
                                                         "client_id": client_id, "url": url}))
    return url


def parse_redirect(text):
    """The pasted redirect URL (or bare code) -> (code, state|None)."""
    text = (text or "").strip()
    if not text:
        raise UsageError(f"empty input: paste the full {REDIRECT}?code=... URL from the browser")
    if "?" not in text and "=" not in text:
        return text, None
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(text).query or text.split("?", 1)[-1])
    if "error" in q:
        raise CliError(f"Google refused the consent: {q['error'][0]}")
    if "code" not in q:
        raise UsageError("no code= in the pasted URL; copy the whole address bar after consenting")
    return q["code"][0], q.get("state", [None])[0]


def finish(prof, cfg, code, state):
    """Exchange the code, store the token. -> account dict. Exit 2 when the Gmail box was left unticked."""
    cid, secret = config.require_client(cfg, prof)
    p = _pending_path(prof)
    if not p.exists():
        raise UsageError("no login in progress: run `gmail login --start` (or `gmail onboard`) first")
    pending = json.loads(p.read_text(encoding="utf-8"))
    if time.time() - pending["created"] > PENDING_TTL:
        raise UsageError("the login URL expired (24 h): start again with `gmail onboard`")
    if state is not None and state != pending["state"]:
        raise UsageError("this redirect URL belongs to another login attempt: use the URL from the latest one")
    try:
        tok = http.request("POST", TOKEN_URL, allow_mutate=True, retries=1, form={
            "code": code, "client_id": cid, "client_secret": secret, "redirect_uri": REDIRECT,
            "grant_type": "authorization_code", "code_verifier": pending["verifier"]})
    except CliError as e:
        err = e.body.get("error") if isinstance(e.body, dict) else None
        if err in ("invalid_client", "unauthorized_client"):
            raise UsageError(f"Google rejected the OAuth client ({err}): import a Desktop app client JSON "
                             f"with `gmail onboard --profile {prof} --client-file PATH`") from None
        if err == "invalid_grant":
            raise UsageError("that code was already used or expired: start the login again") from None
        raise
    if not isinstance(tok, dict) or not tok.get("refresh_token"):
        raise CliError("Google returned no refresh_token; remove the app at myaccount.google.com/permissions "
                       "and log in again")
    p.unlink(missing_ok=True)
    if GMAIL_SCOPE not in (tok.get("scope") or "").split():
        raise UsageError("the Gmail box on Google's consent page was left unticked (token has no Gmail access): "
                         "log in again and tick it (or \"Select all\")", code=2)
    save(prof, tok)
    acct = account_of(tok)
    config.update(prof, account=acct)
    return acct


def account_of(tok):
    """Token response -> {email, domain, refresh_expires_in}. domain = the id_token 'hd' claim
    (Google Workspace only). refresh_token_expires_in = a time-limited refresh token (External
    app left in 'Testing': 7 days)."""
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


def save(prof, tok, refresh_token=None):
    data = {"access_token": tok["access_token"], "refresh_token": tok.get("refresh_token") or refresh_token,
            "expires": time.time() + int(tok.get("expires_in", 3600)), "scope": tok.get("scope")}
    paths.write_private(token_path(prof), json.dumps(data, indent=1) + "\n")
    with _lock:
        _cache[prof] = (data["access_token"], data["expires"])
    return data


def load(prof):
    try:
        return json.loads(token_path(prof).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def granted(prof):
    """Scopes the stored token was granted -> set, or None when unknown (no token / no scope field)."""
    tok = load(prof)
    return set(tok["scope"].split()) if tok and tok.get("scope") else None


def lacks_settings(prof):
    """True when the token is known to miss the filters scope (logged in before it was requested,
    or the box was left unticked)."""
    g = granted(prof)
    return g is not None and SETTINGS_SCOPE not in g


def logged_in(prof):
    tok = load(prof)
    return bool(tok and tok.get("refresh_token"))


def drop(prof):
    """Forget a token that cannot work: the next login replaces it."""
    token_path(prof).unlink(missing_ok=True)
    with _lock:
        _cache.pop(prof, None)


def access_token(prof):
    """A valid access token, refreshed (and written back) when within 60 s of expiry. Thread-safe."""
    with _lock:
        hit = _cache.get(prof)
        if hit and hit[1] > time.time() + 60:
            return hit[0]
        tok = load(prof)
        if not tok or not tok.get("refresh_token"):
            raise UsageError(f"profile {prof!r} is not logged in: run `gmail onboard --profile {prof}`")
        if tok.get("expires", 0) > time.time() + 60:
            _cache[prof] = (tok["access_token"], tok["expires"])
            return tok["access_token"]
        cfg = config.load(prof)
        cid, secret = config.require_client(cfg, prof)
        try:
            new = http.request("POST", TOKEN_URL, allow_mutate=True, retries=2, form={
                "client_id": cid, "client_secret": secret,
                "refresh_token": tok["refresh_token"], "grant_type": "refresh_token"})
        except CliError as e:
            if e.status in (400, 401):  # invalid_grant: revoked, or 7-day expiry of a 'Testing' app
                raise UsageError(f"profile {prof!r}: Google refused the token refresh ({e}) - log in again: "
                                 f"`gmail onboard --profile {prof}`", status=e.status, body=e.body) from None
            raise
        data = {"access_token": new["access_token"], "refresh_token": tok["refresh_token"],
                "expires": time.time() + int(new.get("expires_in", 3600)), "scope": new.get("scope") or tok.get("scope")}
        paths.write_private(token_path(prof), json.dumps(data, indent=1) + "\n")
        _cache[prof] = (data["access_token"], data["expires"])
        return data["access_token"]


def wait_redirect(timeout, prompt):
    """Interactive login: whichever comes first - the browser hitting 127.0.0.1:53682 on this
    machine, or the user pasting the redirect URL at the prompt (headless / remote browser)."""
    import http.server
    import queue

    got = queue.Queue()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            got.put(f"{REDIRECT.rstrip('/')}{self.path}")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"gmail: login received, you can close this tab.\n")

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
