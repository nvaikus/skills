"""Stdlib HTTP layer. Every network call in the CLI goes through `request` (tests patch it)."""
import json
import time
import urllib.error
import urllib.request

UA = "model-cli/1.0 (+https://github.com/nvaikus/skills)"


class HttpError(Exception):
    """Non-2xx response. `body` is the provider's error text, surfaced verbatim."""

    def __init__(self, status, body, url):
        self.status, self.body, self.url = status, body, url
        super().__init__(f"HTTP {status}: {body}")


def request(method, url, *, headers=None, body=None, timeout=60):
    """Return (status, headers_dict, bytes). Raises HttpError on non-2xx."""
    hdrs = {"User-Agent": UA, **(headers or {})}
    data = None
    if body is not None:
        if isinstance(body, (dict, list)):
            data = json.dumps(body).encode()
            hdrs.setdefault("Content-Type", "application/json")
        else:
            data = body if isinstance(body, bytes) else str(body).encode()
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        raise HttpError(e.code, _error_text(raw), url) from None


def _error_text(raw):
    """Pull the human message out of common JSON error shapes; else raw text."""
    try:
        j = json.loads(raw)
    except ValueError:
        return raw.strip()[:2000]
    err = j.get("error", j) if isinstance(j, dict) else j
    if isinstance(err, dict):
        msg = err.get("message") or err.get("error") or json.dumps(err)
        meta = err.get("metadata") or {}
        if isinstance(meta, dict) and meta.get("raw"):
            msg = f"{msg} | {meta['raw']}"
        return str(msg)[:2000]
    return str(err)[:2000]


def get_json(url, *, headers=None, timeout=30):
    return json.loads(request("GET", url, headers=headers, timeout=timeout)[2])


def post_json(url, payload, *, headers=None, timeout=300):
    return json.loads(request("POST", url, headers=headers, body=payload, timeout=timeout)[2])


def with_retry(fn, *, retries=1, wait=3.0, retry_on=(429, 500, 502, 503, 504)):
    """Call fn(); retry on transient statuses. Last error propagates."""
    for attempt in range(retries + 1):
        try:
            return fn()
        except HttpError as e:
            if attempt >= retries or e.status not in retry_on:
                raise
            time.sleep(wait)
