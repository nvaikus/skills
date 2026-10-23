"""Every network call: GET only (vinted never writes to Vinted). Polite: one request per GAP seconds per process,
bounded timeout, few retries. Classifies refusals (Cloudflare challenge) so a 'broken' source is visible (exit 3)
and logged."""
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
TIMEOUT = 25      # seconds per attempt (catalog pages are ~4 MB)
RETRIES = 2       # 429 / 5xx / network only
MAX_WAIT = 30     # a longer Retry-After is reported, not slept through
GAP = 1.5         # min seconds between two requests (VINTED_GAP overrides; tests set 0)

_ctx = None
_lock = threading.Lock()
_last = [0.0]


def tls_context():
    """create_default_context() with post_handshake_auth off: urllib's own default context sets that TLS
    extension, which CDN bot filters fingerprint (proven on OLX's CloudFront 2026-10-21). Keep it off."""
    global _ctx
    with _lock:
        if _ctx is None:
            _ctx = ssl.create_default_context()
            _ctx.post_handshake_auth = False
        return _ctx


def _gap():
    try:
        return float(os.environ.get("VINTED_GAP", GAP))
    except ValueError:
        return GAP


def _pace():
    with _lock:
        wait = _last[0] + _gap() - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.monotonic()


def health(host, path, outcome, detail=""):
    """One line per request outcome in health.tsv: the record of how often the source breaks."""
    try:
        p = paths.root() / "health.tsv"
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"{int(time.time())}\t{host}\t{path}\t{outcome}\t{str(detail)[:200]}\n")
    except OSError:
        pass


def _is_html(text, ctype):
    return "html" in (ctype or "") or text.lstrip()[:15].lower().startswith(("<!doctype", "<html"))


def challenged(text):
    """Cloudflare's JS challenge / interstitial ('Just a moment', 'Enable JavaScript and cookies')."""
    low = text[:20000].lower()
    return "_cf_chl_opt" in low or "challenge-platform" in low or "cf-chl-" in low


def _refusal(status, text, ctype):
    """-> short reason when the response is a bot wall (Cloudflare challenge, captcha), else None."""
    low = text[:20000].lower()
    if challenged(text):
        return "Cloudflare challenge"
    if "captcha" in low and _is_html(text, ctype):
        return "captcha page"
    if status in (403, 429) and _is_html(text, ctype):
        return "Cloudflare refused the request" if "cloudflare" in low else "HTML wall"
    if status == 403:
        return "forbidden"
    return None


def get(url, params=None, want="json", headers=None):
    """-> parsed JSON (want='json'), page text (want='text') or {name: value} of the Set-Cookie headers
    (want='cookies'). Redirects are followed. Raises Broken (exit 3) on a bot wall or HTML where JSON was
    expected; CliError(status=, body=) on other HTTP >= 400; CliError(status=0) on network failure."""
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=True)
    u = urllib.parse.urlparse(url)
    accept = "application/json, text/plain, */*" if want == "json" else "text/html,application/xhtml+xml"
    hdrs = {"User-Agent": UA, "Accept": accept, "Accept-Language": "en;q=0.8", **(headers or {})}
    delay = 2.0
    for attempt in range(RETRIES + 1):
        _pace()
        req = urllib.request.Request(url, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=tls_context()) as r:
                status, ctype, raw = r.status, r.headers.get("Content-Type", ""), r.read()
                cookies = r.headers.get_all("Set-Cookie") or []
        except urllib.error.HTTPError as e:
            status, ctype, raw = e.code, e.headers.get("Content-Type", "") if e.headers else "", e.read() or b""
            cookies = []
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
        text = raw.decode("utf-8", "replace")
        why = _refusal(status, text, ctype)
        if why:
            health(u.netloc, u.path, "blocked", f"{status} {why}")
            raise Broken(f"Vinted blocked the request: HTTP {status}, {why} ({u.netloc}{u.path}). The unofficial "
                         "source refused this client; see references/traps.md 'When it breaks'", status=status)
        if status >= 400:
            body = _json(text)
            health(u.netloc, u.path, "http", status)
            raise CliError(f"HTTP {status} from {u.netloc}{u.path}: {message(body)}", status=status, body=body)
        if want == "cookies":
            health(u.netloc, u.path, "ok")
            return dict(c.split(";", 1)[0].strip().split("=", 1) for c in cookies if "=" in c.split(";", 1)[0])
        if want != "json":
            health(u.netloc, u.path, "ok")
            return text
        body = _json(text)
        if not isinstance(body, dict):
            kind = "HTML instead of JSON" if _is_html(text, ctype) else "not JSON"
            health(u.netloc, u.path, "schema", kind)
            raise Broken(f"Vinted answered {kind} on {u.netloc}{u.path} (HTTP {status}): the endpoint changed or "
                         "a bot wall; see references/traps.md 'When it breaks'", status=status)
        health(u.netloc, u.path, "ok")
        return body


def _json(text):
    try:
        return json.loads(text) if text else None
    except ValueError:
        return text


def message(body):
    """Vinted API errors: {"code", "message", "message_code"}; pages: HTML (shown as 'HTML page')."""
    if isinstance(body, dict):
        return str(body.get("message") or body.get("error") or json.dumps(body))[:300]
    text = str(body or "")
    return "HTML page" if text.lstrip()[:1] == "<" else text[:300]


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
