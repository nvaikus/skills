"""Every network call: GET only (olx never writes to OLX). Polite: one request per GAP seconds per process,
bounded timeout, few retries. Classifies refusals so a 'broken' endpoint is visible (exit 3) and logged."""
import json
import os
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import paths
from .errors import Broken, CliError

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/130.0.0.0 Safari/537.36")
TIMEOUT = 20      # seconds per attempt
RETRIES = 2       # 429 / 5xx / network only
MAX_WAIT = 30     # a longer Retry-After is reported, not slept through
GAP = 1.0         # min seconds between two requests (OLX_GAP overrides; tests set 0)

_ctx = None
_lock = threading.Lock()
_last = [0.0]


def tls_context():
    """Live-proven 2026-10-21, do not 'simplify' back to urlopen's default: CloudFront in front of OLX
    answers 403 to a TLS ClientHello carrying the post_handshake_auth extension, which urllib's own default
    context sets. A plain create_default_context() leaves it off and passes."""
    global _ctx
    with _lock:
        if _ctx is None:
            _ctx = ssl.create_default_context()
            _ctx.post_handshake_auth = False
        return _ctx


def _gap():
    try:
        return float(os.environ.get("OLX_GAP", GAP))
    except ValueError:
        return GAP


def _pace():
    with _lock:
        wait = _last[0] + _gap() - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.monotonic()


def health(host, path, outcome, detail=""):
    """One line per request outcome in health.tsv: the record of how often the endpoint breaks."""
    try:
        p = paths.root() / "health.tsv"
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"{int(time.time())}\t{host}\t{path}\t{outcome}\t{str(detail)[:200]}\n")
    except OSError:
        pass


def _is_html(text, ctype):
    return "html" in (ctype or "") or text.lstrip()[:15].lower().startswith(("<!doctype", "<html"))


def _refusal(status, text, ctype):
    """-> short reason when the response is a bot wall (CloudFront 403, captcha page), else None."""
    low = text[:4000].lower()
    if "captcha" in low or "are you a robot" in low or "px-captcha" in low:
        return "captcha page"
    if status in (403, 429) and _is_html(text, ctype):
        return "CloudFront refused the request" if "cloudfront" in low else "HTML wall"
    if status == 403:
        return "forbidden"
    return None


def get(url, params=None, want="json"):
    """-> parsed JSON (want='json'), text (want='text') or raw bytes (want='bytes', photos). Raises Broken (exit 3) on a bot wall or HTML where
    JSON was expected; CliError(status=, body=) on other HTTP >= 400; CliError(status=0) on network failure."""
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=True)
    u = urllib.parse.urlparse(url)
    accept = {"json": "application/json", "bytes": "image/*,*/*;q=0.8"}.get(want, "text/html,application/xhtml+xml")
    hdrs = {"User-Agent": UA, "Accept": accept, "Accept-Language": "en;q=0.8"}
    delay = 2.0
    for attempt in range(RETRIES + 1):
        _pace()
        req = urllib.request.Request(url, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=tls_context()) as r:
                status, ctype, raw = r.status, r.headers.get("Content-Type", ""), r.read()
        except urllib.error.HTTPError as e:
            status, ctype, raw = e.code, e.headers.get("Content-Type", "") if e.headers else "", e.read() or b""
            if (status == 429 or status >= 500) and attempt < RETRIES:
                try:
                    wait = float(e.headers.get("Retry-After")) if status == 429 else delay
                except (TypeError, ValueError):
                    wait = delay
                if wait <= MAX_WAIT:
                    time.sleep(wait)
                    delay *= 2
                    continue
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            if attempt < RETRIES:
                time.sleep(delay)
                delay *= 2
                continue
            health(u.netloc, u.path, "network", getattr(e, "reason", e))
            raise CliError(f"network error for {u.netloc}{u.path}: {getattr(e, 'reason', e)}", status=0) from None
        if want == "bytes" and status < 400 and not _is_html(raw[:64].decode("latin-1"), ctype):
            health(u.netloc, u.path, "ok")
            return raw
        text = raw.decode("utf-8", "replace")
        why = _refusal(status, text, ctype)
        if why:
            health(u.netloc, u.path, "blocked", f"{status} {why}")
            raise Broken(f"OLX blocked the request: HTTP {status}, {why} ({u.netloc}{u.path}). The unofficial "
                         "endpoint refused this client; see references/traps.md 'When it breaks'", status=status)
        if status >= 400:
            body = _json(text)
            health(u.netloc, u.path, "http", status)
            raise CliError(f"HTTP {status} from {u.netloc}{u.path}: {message(body)}", status=status, body=body)
        if want == "bytes":  # HTML where an image was expected
            health(u.netloc, u.path, "schema", "HTML instead of a file")
            raise Broken(f"OLX answered HTML instead of a file on {u.netloc}{u.path} (HTTP {status})", status=status)
        if want != "json":
            health(u.netloc, u.path, "ok")
            return text
        body = _json(text)
        if not isinstance(body, dict):
            kind = "HTML instead of JSON" if _is_html(text, ctype) else "not JSON"
            health(u.netloc, u.path, "schema", kind)
            raise Broken(f"OLX answered {kind} on {u.netloc}{u.path} (HTTP {status}): the endpoint changed or "
                         "a bot wall; see references/traps.md 'When it breaks'", status=status)
        health(u.netloc, u.path, "ok")
        return body


def _json(text):
    try:
        return json.loads(text) if text else None
    except ValueError:
        return text


def message(body):
    """OLX errors: {"error": {"status", "title", "detail", "validation": [{"field", "title"}]}}."""
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            val = "; ".join(f"{v.get('field')}: {v.get('title')}" for v in err.get("validation") or [] if isinstance(v, dict))
            return val or err.get("detail") or err.get("title") or json.dumps(err)[:300]
        return json.dumps(body)[:300]
    return str(body or "")[:300]


def health_stats(days=30, now=None):
    """-> {outcome: count} over the last `days` + the newest failure line (or None)."""
    now = now or time.time()
    p = paths.root_peek() / "health.tsv"
    counts, last_fail = {}, None
    if not p.exists():
        return counts, None
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split("\t")
        if len(parts) < 4 or not parts[0].isdigit() or now - int(parts[0]) > days * 86400:
            continue
        counts[parts[3]] = counts.get(parts[3], 0) + 1
        if parts[3] != "ok":
            last_fail = parts
    return counts, last_fail
