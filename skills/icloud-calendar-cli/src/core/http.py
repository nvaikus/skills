"""Every network call. Transport rail: PUT/DELETE/POST/MKCOL... need allow_mutate=True, which only
api/dav.mutate passes. PROPFIND and REPORT are reads. `grep -rn allow_mutate src/commands/` stays empty.
Redirects are followed by hand (urllib drops the method and body of a PROPFIND on 301), credentials
only ever go to https hosts under icloud.com unless the test hook says otherwise."""
import base64
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .errors import CliError

UA = "icloud-calendar"
READS = {"GET", "HEAD", "PROPFIND", "REPORT", "OPTIONS"}
TRUSTED = (".icloud.com",)

_ctx = None
_ctx_lock = threading.Lock()


def tls_context():
    global _ctx
    with _ctx_lock:
        if _ctx is None:
            _ctx = ssl.create_default_context()
        return _ctx


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


_opener = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=tls_context()))


class Response:
    def __init__(self, status, headers, body, url):
        self.status, self.headers, self.body, self.url = status, headers, body, url

    def header(self, name):
        return (self.headers or {}).get(name)

    @property
    def text(self):
        return (self.body or b"").decode("utf-8", "replace")


def trusted(url):
    p = urllib.parse.urlsplit(url)
    host = (p.hostname or "").lower()
    return p.scheme == "https" and any(host == t.lstrip(".") or host.endswith(t) for t in TRUSTED)


def _send(method, url, data, hdrs, timeout):
    """-> Response for any status (urllib raises on >= 300; we turn it back into a Response)."""
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with _opener.open(req, timeout=timeout) as r:
            return Response(r.status, dict(r.headers), r.read(), url)
    except urllib.error.HTTPError as e:
        return Response(e.code, dict(e.headers or {}), e.read(), url)


def request(method, url, body=None, headers=None, auth=None, allow_mutate=False, timeout=60, retries=3,
            ok=(200, 201, 204, 207)):
    """-> Response with status in `ok`. Raises CliError(status=, body=) otherwise.
    Reads retry on 5xx/429/network; a mutation retries only on 429/503 (the server did not run it)."""
    method = method.upper()
    if method not in READS and not allow_mutate:
        raise RuntimeError(f"transport rail: {method} {url} without allow_mutate")
    data = body.encode("utf-8") if isinstance(body, str) else body
    hdrs = {"User-Agent": UA, **(headers or {})}
    delay, hops = 1.0, 0
    attempt = 0
    while True:
        h = dict(hdrs)
        if auth and trusted(url):
            h["Authorization"] = "Basic " + base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
        try:
            r = _send(method, url, data, h, timeout)
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            if method in READS and attempt < retries:
                attempt += 1
                time.sleep(delay)
                delay *= 2
                continue
            reason = getattr(e, "reason", e)
            raise CliError(f"network error for {url}: {reason}"
                           + ("" if method in READS else " - the change may or may not have applied; re-read"),
                           status=0) from None
        if r.status in (301, 302, 307, 308) and r.header("Location") and hops < 5:
            url, hops = urllib.parse.urljoin(url, r.header("Location")), hops + 1
            continue
        if r.status in ok:
            return r
        retry = r.status in (429, 503) or (method in READS and r.status >= 500)
        if retry and attempt < retries:
            attempt += 1
            after = retry_after(r.headers)
            time.sleep(min(after, 30) if after is not None else delay)
            delay *= 2
            continue
        raise CliError(f"HTTP {r.status} from {method} {url}: {summary(r.text)}", status=r.status, body=r.text)


def retry_after(headers):
    try:
        v = float((headers or {}).get("Retry-After") or "")
    except (TypeError, ValueError):
        return None
    return v if v >= 0 else None


def summary(text):
    """One line out of an error body (XML / HTML / text)."""
    import re
    t = re.search(r"<title[^>]*>(.*?)</title>", text or "", re.I | re.S)
    if t:
        return "html page: " + " ".join(t.group(1).split())[:120]
    plain = re.sub(r"<[^>]+>", " ", text or "")
    return " ".join(plain.split())[:200] or "(empty body)"
