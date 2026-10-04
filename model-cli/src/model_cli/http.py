"""Stdlib HTTP layer. Every network call in the CLI goes through `request` (tests patch it)."""
import json
import sys
import time
import urllib.error
import urllib.request
import uuid

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
    if isinstance(j, list) and len(j) == 1 and isinstance(j[0], dict):  # Google: [{"error": {...}}]
        j = j[0]
    if isinstance(j, dict) and isinstance(j.get("errors"), list) and j["errors"]:  # Cloudflare v4 envelope
        return "; ".join(str(e.get("message", e)) if isinstance(e, dict) else str(e) for e in j["errors"])[:2000]
    if isinstance(j, dict) and "error" not in j and isinstance(j.get("detail"), (str, list)):  # FastAPI-style
        return str(j["detail"])[:2000]
    err = j.get("error", j) if isinstance(j, dict) else j
    if isinstance(err, dict):
        msg = err.get("message") or err.get("error") or json.dumps(err)
        meta = err.get("metadata") or {}
        if isinstance(meta, dict) and meta.get("raw"):
            msg = f"{msg} | {meta['raw']}"
        return str(msg)[:2000]
    return str(err)[:2000]


def multipart(fields, files):
    """-> (body_bytes, content_type). fields: {name: value}; files: {name: (filename, bytes, mime)}."""
    boundary = f"----model-cli-{uuid.uuid4().hex}"
    out = []
    for k, v in fields.items():
        if isinstance(v, (dict, list, bool)):
            v = json.dumps(v)
        out.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    for k, (fname, data, mime) in files.items():
        out.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"; filename="{fname}"\r\n'
                   f"Content-Type: {mime}\r\n\r\n".encode() + data + b"\r\n")
    out.append(f"--{boundary}--\r\n".encode())
    return b"".join(out), f"multipart/form-data; boundary={boundary}"


def get_json(url, *, headers=None, timeout=30):
    return json.loads(request("GET", url, headers=headers, timeout=timeout)[2])


def post_json(url, payload, *, headers=None, timeout=300):
    return json.loads(request("POST", url, headers=headers, body=payload, timeout=timeout)[2])


def with_retry(fn, *, retries=1, wait=3.0, backoff=1.0, retry_on=(429, 500, 502, 503, 504)):
    """Call fn(); retry on transient statuses, sleeping wait * backoff**attempt. Last error propagates."""
    for attempt in range(retries + 1):
        try:
            return fn()
        except HttpError as e:
            if attempt >= retries or e.status not in retry_on:
                raise
            delay = wait * backoff ** attempt
            print(f"# HTTP {e.status}; retry {attempt + 1}/{retries} in {delay:g}s", file=sys.stderr)
            time.sleep(delay)
