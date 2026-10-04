"""Every network call. Transport rail: anything but GET needs allow_mutate=True, which only
api/google.mutate and api/auth (token endpoint) pass. `grep -rn allow_mutate src/commands/` must stay empty."""
import base64
import json
import re
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .errors import CliError

UA = "gmail-cli"

_ctx = None
_ctx_lock = threading.Lock()


def tls_context():
    """One TLS context per process. urlopen without `context=` builds a fresh one per call and re-reads
    the whole CA bundle (set_default_verify_paths): ~10 ms alone, ~0.7 s CPU each when threads contend
    - a 9-profile search burned 45 s of CPU on it."""
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


def request(method, url, params=None, body=None, form=None, headers=None, allow_mutate=False,
            basic=None, timeout=60, retries=3, data=None, content_type=None, rate_retry=True):
    """-> parsed JSON (or text, or None). Raises CliError(status=, body=, retry_after=) on HTTP >= 400.
    GET retries on 429/5xx/network; a mutation retries only on 429 (the server did not run it).
    rate_retry=False: 429 is raised at once - the caller (api/google) paces and backs off itself."""
    if method != "GET" and not allow_mutate:
        raise RuntimeError(f"transport rail: {method} {url} without allow_mutate")
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=True)
    hdrs = {"User-Agent": UA, **(headers or {})}
    if data is not None:  # raw bytes (multipart upload)
        hdrs["Content-Type"] = content_type or "application/octet-stream"
    elif form is not None:
        data = urllib.parse.urlencode(form).encode()
        hdrs["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode()
        hdrs["Content-Type"] = "application/json"
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
            retry = (e.code == 429 and rate_retry) or (method == "GET" and e.code >= 500)
            after = retry_after(e.headers)
            if retry and attempt < retries:
                time.sleep(min(after, 30) if after else delay)
                delay *= 2
                continue
            err = CliError(f"HTTP {e.code} from {url.split('?')[0]}: {_msg(parsed)}", status=e.code, body=parsed)
            err.retry_after = after
            raise err from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if method == "GET" and attempt < retries:
                time.sleep(delay)
                delay *= 2
                continue
            reason = getattr(e, "reason", e)
            raise CliError(f"network error for {url.split('?')[0]}: {reason}"
                           + ("" if method == "GET" else " - the change may or may not have applied; re-read"),
                           status=0) from None


def retry_after(headers):
    """Retry-After seconds (delta form only; Google sends that) or None."""
    try:
        v = float((headers or {}).get("Retry-After") or "")
    except (TypeError, ValueError):
        return None
    return v if v >= 0 else None


def _msg(parsed):
    if isinstance(parsed, dict):
        err = parsed.get("error")
        if isinstance(err, dict):
            return err.get("message") or json.dumps(err)[:300]
        if err:
            return f"{err}: {parsed.get('error_description', '')}".strip(": ")
        return json.dumps(parsed)[:300]
    text = str(parsed or "")
    if re.search(r"<\s*(!doctype|html|head|body)\b", text[:1000], re.I):  # an error page, not a message
        t = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
        return f"html page: {' '.join(t.group(1).split())[:120]}" if t else "html page"
    return " ".join(text.split())[:300]
