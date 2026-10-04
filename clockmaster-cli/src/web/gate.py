"""Who may use the UI. The UI can create tasks = run any shell command as this
user, so every request passes `check` before routing.

- Direct local request (local Host, no proxy headers): allowed — local browser,
  SSH tunnel. Same trust as before the gate.
- Anything else is "proxied" (a forwarding/Tailscale header, or a non-local
  Host — that also stops DNS rebinding): it must carry exactly one
  `Tailscale-User-Login` listed in <data>/ui-allow.txt. `tailscale serve`
  deletes client copies of its identity headers and of X-Forwarded-For and sets
  its own; it sets NO login for tagged devices or funnel (public) traffic, so a
  missing login = reject.
- Writes (non-GET) must not come cross-site (Origin / Sec-Fetch-Site): the
  identity is per device, not per cookie, so any page open on the owner's
  phone could otherwise POST a task.
"""
from urllib.parse import urlsplit

import identity

LOGIN = "Tailscale-User-Login"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
PROXY_HEADERS = ("X-Forwarded-For", "X-Forwarded-Host", "X-Forwarded-Proto", "X-Real-IP", "Forwarded",
                 "Via", "Tailscale-Headers-Info", LOGIN, "Tailscale-User-Name", "Tailscale-Funnel-Request")
SAFE_METHODS = ("GET", "HEAD")


def allow_file():
    return identity.data_dir() / "ui-allow.txt"


def allowed():
    """Allowed logins, lower-case. `#` comments and blank lines skipped."""
    try:
        lines = allow_file().read_text(encoding="utf-8").splitlines()
    except OSError:
        return set()
    return {ln.split("#", 1)[0].strip().lower() for ln in lines} - {""}


def allow(login):
    """Add a login to the allow file; True when it was new."""
    login = login.strip().lower()
    if login in allowed():
        return False
    p = allow_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    head = "" if p.exists() else (f"# Tailscale logins allowed to use the {identity.APP} UI through "
                                  "`tailscale serve`, one per line\n")
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(head + login + "\n")
    return True


def _host(value):
    try:
        return (urlsplit("//" + value).hostname or "") if value else ""
    except ValueError:
        return "?"


def proxied(headers):
    return any(h in headers for h in PROXY_HEADERS) or _host(headers.get("Host", "")) not in LOCAL_HOSTS | {""}


def check(method, headers):
    """None = let it through; else the reason for a 403."""
    if proxied(headers):
        if headers.get("Tailscale-Funnel-Request"):
            return "public (funnel) requests are refused"
        logins = headers.get_all(LOGIN) or []
        if len(logins) != 1 or not logins[0].strip():
            return "no Tailscale identity on a proxied request (tagged device, funnel or a foreign proxy)"
        login = logins[0].strip().lower()
        if login not in allowed():
            return f"{login} is not allowed to use this UI"
    if method not in SAFE_METHODS:
        if headers.get("Sec-Fetch-Site", "").lower() == "cross-site":
            return "cross-site write refused"
        origin = headers.get("Origin")
        if origin is not None and urlsplit(origin).netloc.lower() != headers.get("Host", "").lower():
            return "cross-origin write refused"
    return None
