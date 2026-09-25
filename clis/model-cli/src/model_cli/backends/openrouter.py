"""OpenRouter: catalog /api/v1/models (keyless) + chat completions (text, vision, image output)."""
import base64
import json
import mimetypes
import os
from pathlib import Path

from .. import http
from ..core import CliError, MissingToken, UsageError, out_path, sniff_ext

NAME = "openrouter"
ENV = "OPENROUTER_API_KEY"
SIGNUP = "https://openrouter.ai/settings/keys"
BASE = "https://openrouter.ai/api/v1"
_catalog = None


def available(task=None):
    return bool(os.environ.get(ENV))


def catalog():
    global _catalog
    if _catalog is None:
        _catalog = http.get_json(f"{BASE}/models")["data"]
    return _catalog


def _prices(m):
    out = {}
    for k, v in (m.get("pricing") or {}).items():
        try:
            out[k] = float(v)
        except (TypeError, ValueError):
            continue  # non-numeric entries (e.g. "overrides")
    return out


def is_free(m):
    return all(v == 0 for v in _prices(m).values())


def task_of(m):
    arch = m.get("architecture") or {}
    outs, ins = arch.get("output_modalities") or ["text"], arch.get("input_modalities") or ["text"]
    if "image" in outs:
        return "image"
    if "audio" in outs:
        return "audio"
    if "image" in ins or "audio" in ins or "video" in ins:
        return "vision"
    return "llm"


def _task_match(m, task):
    if not task:
        return True
    arch = m.get("architecture") or {}
    outs, ins = arch.get("output_modalities") or [], arch.get("input_modalities") or []
    return {
        "text-to-image": "image" in outs,
        "image-to-image": "image" in outs and "image" in ins,
        "text-to-audio": "audio" in outs,
        "text-to-speech": "audio" in outs,
        "automatic-speech-recognition": "audio" in ins and "text" in outs,
        "text-generation": "text" in outs,
        "image-text-to-text": "image" in ins and "text" in outs,
    }.get(task, False)


def _price_str(m):
    p = _prices(m)
    if is_free(m):
        return "0"
    parts = []
    if p.get("prompt") or p.get("completion"):
        parts.append(f"${p.get('prompt', 0) * 1e6:g}/${p.get('completion', 0) * 1e6:g} per 1M tok")
    if p.get("image_output"):
        parts.append(f"img-out ${p['image_output'] * 1e6:g}/1M")
    return "; ".join(parts) or "paid"


def _row(m):
    return {
        "id": f"{NAME}:{m['id']}",
        "backend": NAME,
        "task": task_of(m),
        "free": "yes" if is_free(m) else "no",
        "price": _price_str(m),
        "popularity": "-",
        "providers": "",
    }


def _score(m, words):
    hay_id = (m["id"] + " " + (m.get("name") or "")).lower()
    hay_desc = (m.get("description") or "").lower()
    if all(w in hay_id for w in words):
        return 2
    if all(w in hay_id + " " + hay_desc for w in words):
        return 1
    return 0


def search(query, task, free, limit):
    words = (query or "").lower().split()
    hits = []
    for m in catalog():
        if not _task_match(m, task) or (free and not is_free(m)):
            continue
        s = _score(m, words) if words else 1
        if s:
            hits.append((s, m.get("created", 0), m))
    hits.sort(key=lambda t: (-t[0], -t[1]))  # id/name match first, newest first
    return [_row(m) for _, _, m in hits[:limit]]


def lookup(model_id):
    for m in catalog():
        if m["id"] == model_id or m.get("canonical_slug") == model_id:
            row = _row(m)
            row["task_full"] = {"image": "text-to-image", "audio": "text-to-audio",
                                "vision": "image-text-to-text"}.get(row["task"], "text-generation")
            row["is_free"] = is_free(m)
            row["_raw"] = m
            return row
    return None


def info(model_id):
    meta = lookup(model_id)
    if not meta:
        raise CliError(f"openrouter: model not found: {model_id}")
    m = meta.pop("_raw")
    arch = m.get("architecture") or {}
    defaults = m.get("default_parameters") or {}
    meta.update({
        "context_length": m.get("context_length"),
        "input": ",".join(arch.get("input_modalities") or []),
        "output": ",".join(arch.get("output_modalities") or []),
        "params": [{"name": p, "type": "", "default": defaults.get(p, ""), "description": ""}
                   for p in m.get("supported_parameters") or []],
    })
    return meta


def _file_part(path):
    mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
    data = Path(path).read_bytes()
    b64 = base64.b64encode(data).decode()
    if mime.startswith("image/"):
        return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}
    if mime.startswith("audio/"):
        fmt = Path(path).suffix.lstrip(".").lower() or "wav"
        return {"type": "input_audio", "input_audio": {"data": b64, "format": fmt}}
    if mime == "application/pdf":
        return {"type": "file", "file": {"filename": Path(path).name, "file_data": f"data:{mime};base64,{b64}"}}
    return {"type": "text", "text": data.decode("utf-8", "replace")}


def run(model_id, task, inp, params, out, cfg):
    if not available():
        raise MissingToken(ENV, SIGNUP)
    content = inp["text"]
    if inp.get("file"):
        content = [{"type": "text", "text": inp["text"]}, _file_part(inp["file"])]
    payload = {"model": model_id, "messages": [{"role": "user", "content": content}], **params}
    if task in ("text-to-image", "image-to-image"):
        payload.setdefault("modalities", ["image", "text"])
    if task in ("text-to-audio", "text-to-speech"):
        raise UsageError("openrouter: audio-output models are not wired yet (need streaming)")
    try:
        r = http.post_json(f"{BASE}/chat/completions", payload,
                           headers={"Authorization": f"Bearer {os.environ[ENV]}",
                                    "X-Title": "model-cli"})
    except http.HttpError as e:
        raise CliError(f"openrouter: HTTP {e.status}: {e.body}") from None
    if r.get("error"):
        raise CliError(f"openrouter: {http._error_text(json.dumps(r))}")
    msg = r["choices"][0]["message"]
    res = {"cost": (r.get("usage") or {}).get("cost")}
    if r.get("model"):
        res["served_by"] = r["model"]
    images = msg.get("images") or []
    if images:
        url = images[0]["image_url"]["url"]
        data = base64.b64decode(url.split(",", 1)[1]) if url.startswith("data:") else http.request("GET", url)[2]
        p = out_path(out, inp["text"], sniff_ext(data, "png"))
        p.write_bytes(data)
        res["path"] = str(p)
        if msg.get("content"):
            res["text"] = msg["content"]
        return res
    res["text"] = msg.get("content") or ""
    return res
