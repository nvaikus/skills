"""Every network call. Read-only rail: anything but GET needs allow_mutate=True, which only api/auth
(token endpoint) passes. `grep -rn allow_mutate src/commands/` must stay empty."""
import base64
import json
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .errors import CliError

UA = "ebay-cli"
MAX_WAIT = 30  # seconds: a longer Retry-After is reported, not slept through

_ctx = None
_ctx_lock = threading.Lock()


def tls_context():
    """One TLS context per process (a fresh one per urlopen re-reads the CA bundle)."""
    global _ctx
    with _ctx_lock:
        if _ctx is None:
            _ctx = ssl.create_default_context()
        return _ctx


def _body(raw):
    text = raw.decode("utf-8", "replace") if raw else ""
    try:
        return json.loads(text) if text else None
    except ValueError:
        return text


def _retry_after(e, default):
    try:
        return float(e.headers.get("Retry-After"))
    except (TypeError, ValueError, AttributeError):
        return default


def request(method, url, params=None, form=None, headers=None, allow_mutate=False, basic=None,
            timeout=30, retries=3):
    """-> parsed JSON (or text, or None). Raises CliError(status=, body=) on HTTP >= 400.
    Retries 429 (honours Retry-After up to MAX_WAIT), GET 5xx and network errors."""
    if method != "GET" and not allow_mutate:
        raise RuntimeError(f"read-only rail: {method} {url} without allow_mutate")
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=True)
    hdrs = {"User-Agent": UA, "Accept": "application/json", **(headers or {})}
    data = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        hdrs["Content-Type"] = "application/x-www-form-urlencoded"
    if basic:
        hdrs["Authorization"] = "Basic " + base64.b64encode(f"{basic[0]}:{basic[1]}".encode()).decode()
    delay = 1.0
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=tls_context()) as r:
                return _body(r.read())
        except urllib.error.HTTPError as e:
            parsed = _body(e.read())
            wait = _retry_after(e, delay) if e.code == 429 else delay
            retry = e.code == 429 or (method == "GET" and e.code >= 500)
            if retry and attempt < retries and wait <= MAX_WAIT:
                time.sleep(wait)
                delay *= 2
                continue
            raise CliError(f"HTTP {e.code} from {url.split('?')[0]}: {message(parsed)}", status=e.code,
                           body=parsed) from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if method == "GET" and attempt < retries:
                time.sleep(delay)
                delay *= 2
                continue
            raise CliError(f"network error for {url.split('?')[0]}: {getattr(e, 'reason', e)}", status=0) from None


def message(parsed):
    """eBay REST errors: {"errors": [{"errorId", "message", "longMessage"}]}; OAuth: {"error", "error_description"}."""
    if isinstance(parsed, dict):
        errs = parsed.get("errors")
        if isinstance(errs, list) and errs and isinstance(errs[0], dict):
            return "; ".join(f"{x.get('longMessage') or x.get('message')} (errorId {x.get('errorId')})" for x in errs[:3])
        if parsed.get("error"):
            return f"{parsed['error']}: {parsed.get('error_description', '')}".strip(": ")
        return json.dumps(parsed)[:300]
    return str(parsed or "")[:300]


def error_ids(e):
    body = e.body if isinstance(e.body, dict) else {}
    return {x.get("errorId") for x in body.get("errors") or [] if isinstance(x, dict)}
