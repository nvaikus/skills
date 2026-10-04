"""Pollinations: keyless fallback. Anonymous = legacy GET endpoints, server-picked model only.
With POLLINATIONS_API_KEY: gen.pollinations.ai, any catalog model (pollen-billed)."""
import os
import urllib.parse
from pathlib import Path

from .. import http
from ..core import CliError, MissingToken, UsageError, out_path, sniff_ext

NAME = "pollinations"
ENV = "POLLINATIONS_API_KEY"
SIGNUP = "https://enter.pollinations.ai/keys"
GEN = "https://gen.pollinations.ai"
ANON_IMAGE = "https://image.pollinations.ai/prompt/"
ANON_TEXT = "https://text.pollinations.ai/"
CAT_TASK = {"image": "text-to-image", "video": "text-to-video", "audio": "text-to-speech",
            "text": "text-generation"}
# Anonymous tier: only the server-picked "default" model works without a key (image / llm).
_catalog = None


def available(task=None):
    if os.environ.get(ENV):
        return True
    return task in (None, "text-to-image", "text-generation")


def catalog():
    global _catalog
    if _catalog is None:
        _catalog = http.get_json(f"{GEN}/models")
    return _catalog


def _row(m):
    cat = m.get("category", "")
    price = ", ".join(f"{k}={v}" for k, v in (m.get("pricing") or {}).items() if k != "currency")
    return {"id": f"{NAME}:{m['name']}", "backend": NAME,
            "task": {"image": "image", "video": "video", "audio": "tts", "text": "llm"}.get(cat, cat),
            "free": "key", "price": f"pollen {price}" if price else "-",
            "popularity": (m.get("health") or {}).get("requests", "-"), "providers": ""}


def _anon_rows(task):
    rows = []
    for t, short in (("text-to-image", "image"), ("text-generation", "llm")):
        if task in (None, t):
            rows.append({"id": f"{NAME}:default", "backend": NAME, "task": short, "free": "yes",
                         "price": "0 (anonymous)", "popularity": "-", "providers": ""})
    return rows


def search(query, task, free, limit):
    words = (query or "").lower().split()
    rows = _anon_rows(task) if not words or all(w in "pollinations default" for w in words) else []
    if free and not os.environ.get(ENV):
        return rows[:limit]
    for m in catalog():
        if task and CAT_TASK.get(m.get("category")) != task:
            continue
        hay = " ".join([m["name"], *(m.get("aliases") or []), m.get("title") or "", m.get("description") or ""]).lower()
        if all(w in hay for w in words) and not m.get("paid_only"):
            rows.append(_row(m))
    return rows[:limit]


def lookup(model_id):
    if model_id == "default":
        return {"id": f"{NAME}:default", "backend": NAME, "task": "", "task_full": "",
                "free": "yes", "is_free": True}
    for m in catalog():
        if model_id == m["name"] or model_id in (m.get("aliases") or []):
            row = _row(m)
            row["task_full"] = CAT_TASK.get(m.get("category"), "")
            row["is_free"] = True  # pollen-billed only with a key; no key -> refused anyway
            row["_raw"] = m
            return row
    return None


def info(model_id):
    meta = lookup(model_id)
    if not meta:
        raise CliError(f"pollinations: model not found: {model_id}")
    m = meta.pop("_raw", {})
    names = m.get("supported_parameters") or []
    if model_id == "default":
        names = ["width", "height", "seed", "enhance", "nologo (image)", "system", "temperature (llm)"]
    meta["params"] = [{"name": n, "type": "", "default": "", "description": ""} for n in names]
    if m.get("voices"):
        meta["voices"] = ",".join(m["voices"])
    return meta


def _get(url, headers=None):
    # legacy anonymous endpoints are slow (~40 s) and 5xx on upstream rate limits: one retry
    return http.with_retry(lambda: http.request("GET", url, headers=headers, timeout=180), retries=1, wait=5)


def run(model_id, task, inp, params, out, cfg):
    key = os.environ.get(ENV)
    text = inp["text"]
    if inp.get("file"):
        raise UsageError("pollinations: file input is not supported; use hf or openrouter")
    q = {k: v for k, v in params.items()}
    if model_id != "default":
        if not key:
            raise MissingToken(ENV, SIGNUP)
        q["model"] = model_id
    headers = {"Authorization": f"Bearer {key}"} if key else None
    enc = urllib.parse.quote(text, safe="")
    try:
        if task == "text-to-image":
            q.setdefault("nologo", "true")
            base = f"{GEN}/image/" if key else ANON_IMAGE
            _, h, data = _get(f"{base}{enc}?{urllib.parse.urlencode(q)}", headers)
            if "json" in (h.get("Content-Type") or ""):
                raise CliError(f"pollinations: {http._error_text(data.decode('utf-8', 'replace'))}")
        elif task == "text-generation":
            base = f"{GEN}/text/" if key else ANON_TEXT
            _, _, data = _get(f"{base}{enc}?{urllib.parse.urlencode(q)}", headers)
            return {"text": data.decode("utf-8", "replace").strip(), "cost": 0 if not key else None}
        elif task in ("text-to-speech", "text-to-video"):
            kind = "audio" if task == "text-to-speech" else "video"
            _, _, data = _get(f"{GEN}/{kind}/{enc}?{urllib.parse.urlencode(q)}", headers)
        else:
            raise UsageError(f"pollinations: task {task} not supported")
    except http.HttpError as e:
        raise CliError(f"pollinations: HTTP {e.status}: {e.body}") from None
    p = out_path(out, text, sniff_ext(data, {"text-to-image": "jpg", "text-to-speech": "mp3"}.get(task, "mp4")))
    Path(p).write_bytes(data)
    return {"path": str(p), "cost": 0 if not key else None}
