"""Every network call. Transport rail: anything but GET needs allow_mutate=True, which only
api/google.mutate, api/auth (token endpoint) and api/rclone.rc (local rc protocol is POST) pass.
`grep -rn allow_mutate src/commands/` must stay empty."""
import base64
import json
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .errors import CliError

UA = "gdrive-cli"

_ctx = None
_ctx_lock = threading.Lock()


def tls_context():
    """One TLS context per process. urlopen without `context=` builds a fresh one per call and re-reads
    the whole CA bundle (set_default_verify_paths): ~10 ms alone, ~0.7 s CPU each when threads contend."""
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
            basic=None, timeout=60, retries=3):
    """-> parsed JSON (or text, or None). Raises CliError(status=, body=) on HTTP >= 400.
    GET retries on 429/5xx/network; a mutation retries only on 429 (the server did not run it)."""
    if method != "GET" and not allow_mutate:
        raise RuntimeError(f"transport rail: {method} {url} without allow_mutate")
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=True)
    hdrs = {"User-Agent": UA, **(headers or {})}
    data = None
    if form is not None:
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
            retry = e.code == 429 or (method == "GET" and e.code >= 500)
            if retry and attempt < retries:
                time.sleep(delay)
                delay *= 2
                continue
            raise CliError(f"HTTP {e.code} from {url.split('?')[0]}: {_msg(parsed)}", status=e.code,
                           body=parsed) from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if method == "GET" and attempt < retries:
                time.sleep(delay)
                delay *= 2
                continue
            reason = getattr(e, "reason", e)
            raise CliError(f"network error for {url.split('?')[0]}: {reason}"
                           + ("" if method == "GET" else " - the change may or may not have applied; re-read"),
                           status=0) from None


def _msg(parsed):
    if isinstance(parsed, dict):
        err = parsed.get("error")
        if isinstance(err, dict):
            return err.get("message") or json.dumps(err)[:300]
        if err:
            return f"{err}: {parsed.get('error_description', '')}".strip(": ")
        return json.dumps(parsed)[:300]
    return str(parsed or "")[:300]


def download(url, dest, timeout=120, headers=None, params=None):
    """GET url into file dest (streamed). HTTP errors keep status + parsed body."""
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=tls_context()) as r, open(dest, "wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
    except urllib.error.HTTPError as e:
        parsed = _body(e.read())
        raise CliError(f"HTTP {e.code} downloading {url.split('?')[0]}: {_msg(parsed)}", status=e.code,
                       body=parsed) from None
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise CliError(f"network error downloading {url.split('?')[0]}: {getattr(e, 'reason', e)}", status=0) from None


def get_text(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=tls_context()) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raise CliError(f"HTTP {e.code} from {url}", status=e.code) from None
    except urllib.error.URLError as e:
        raise CliError(f"network error for {url}: {e.reason}") from None
