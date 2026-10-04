"""OAuth client-credentials (application token). Cached in token.json until 5 min before expiry,
keyed by a hash of the App ID so a key change never reuses a stale token."""
import hashlib
import json
import threading
import time

from ..core import http, paths, secrets
from ..core.errors import CliError, UsageError

TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
SCOPE = "https://api.ebay.com/oauth/api_scope"
MARGIN = 300
_lock = threading.Lock()


def _path():
    return paths.root_peek() / "token.json"


def _kid(cid):
    return hashlib.sha256(cid.encode()).hexdigest()[:16]


def keys():
    cid, sec, _ = secrets.client()
    if not cid or not sec:
        miss = " and ".join(k for k, v in zip(secrets.KEYS, (cid, sec)) if not v)
        raise UsageError(f"no eBay keys ({miss} missing): run `ebay setup` (it walks the user through it)")
    return cid, sec


def mint(cid, sec):
    """-> (token, expires_at). Errors translated to what the user must do."""
    try:
        r = http.request("POST", TOKEN_URL, form={"grant_type": "client_credentials", "scope": SCOPE},
                         basic=(cid, sec), allow_mutate=True)
    except CliError as e:
        code = (e.body or {}).get("error") if isinstance(e.body, dict) else None
        if code == "invalid_client" or e.status == 401:
            raise UsageError("eBay refused the keys (invalid_client): App ID / Cert ID wrong, swapped, from the "
                             "Sandbox keyset, or the production keyset is still disabled (account-deletion "
                             "opt-out missing). Run `ebay setup`.", body=e.body) from None
        if code == "invalid_scope":
            raise UsageError("eBay refused the scope: the keyset lacks public Browse access - check the "
                             "production keyset at developer.ebay.com/my/keys", body=e.body) from None
        raise
    return r["access_token"], time.time() + int(r.get("expires_in", 7200))


def access_token(force=False):
    with _lock:
        cid, sec = keys()
        p, kid = _path(), _kid(cid)
        if not force and p.exists():
            try:
                t = json.loads(p.read_text())
                if t.get("kid") == kid and t.get("expires_at", 0) - MARGIN > time.time():
                    return t["access_token"]
            except (ValueError, KeyError):
                pass
        tok, exp = mint(cid, sec)
        paths.write_private(p, json.dumps({"kid": kid, "access_token": tok, "expires_at": exp}) + "\n")
        return tok


def drop():
    try:
        _path().unlink()
    except OSError:
        pass
