"""Hugging Face: Hub API (stdlib) for search/info; huggingface_hub.InferenceClient for run."""
import inspect
import os
import urllib.parse
from pathlib import Path

from .. import http
from ..core import CliError, MissingToken, UsageError, out_path, sniff_ext, short_task

NAME = "hf"
ENV = "HF_TOKEN"
SIGNUP = "https://huggingface.co/settings/tokens"
HUB = "https://huggingface.co/api/models"
SPEC = "https://raw.githubusercontent.com/huggingface/huggingface.js/main/packages/tasks/src/tasks/{}/spec/input.json"
EXPAND = ["inferenceProviderMapping", "pipeline_tag", "likes", "downloads"]
# chat tasks share the chat-completion spec
SPEC_TASK = {"text-generation": "chat-completion", "image-text-to-text": "chat-completion"}
CLIENT_METHOD = {
    "text-to-image": "text_to_image",
    "text-to-video": "text_to_video",
    "text-to-speech": "text_to_speech",
    "automatic-speech-recognition": "automatic_speech_recognition",
    "text-generation": "chat_completion",
    "image-text-to-text": "chat_completion",
}
DEFAULT_EXT = {"text-to-image": "png", "text-to-video": "mp4", "text-to-speech": "wav", "text-to-audio": "wav"}


def available(task=None):
    return bool(os.environ.get(ENV))


def _qs(params):
    return urllib.parse.urlencode(params, doseq=True)


def _live(m):
    mp = m.get("inferenceProviderMapping") or []
    if isinstance(mp, dict):  # single-model endpoint returns a dict keyed by provider
        mp = [dict(v, provider=k) for k, v in mp.items()]
    return [p for p in mp if p.get("status") == "live"]


def _row(m):
    live = _live(m)
    task = m.get("pipeline_tag") or (live[0].get("task") if live else "")
    return {
        "id": f"{NAME}:{m['id']}",
        "backend": NAME,
        "task": short_task(task),
        "free": "credit",
        "price": "-",
        "popularity": m.get("likes", 0),
        "providers": ",".join(p["provider"] for p in live),
    }


def search(query, task, free, limit):
    params = {"inference_provider": "all", "sort": "likes", "limit": max(limit * 2, 20), "expand[]": EXPAND}
    if query:
        params["search"] = query
    if task:
        params["pipeline_tag"] = task
    rows = [_row(m) for m in http.get_json(f"{HUB}?{_qs(params)}") if _live(m)]
    return rows[:limit]


def lookup(model_id):
    try:
        m = http.get_json(f"{HUB}/{model_id}?{_qs({'expand[]': EXPAND})}")
    except http.HttpError as e:
        if e.status in (401, 404):
            return None
        raise
    row = _row(m)
    row["task_full"] = m.get("pipeline_tag") or ""
    row["live"] = bool(_live(m))
    return row


def info(model_id):
    meta = lookup(model_id)
    if not meta:
        raise CliError(f"hf: model not found: {model_id}")
    params = []
    spec_task = SPEC_TASK.get(meta["task_full"], meta["task_full"])
    try:
        spec = http.get_json(SPEC.format(spec_task))
        params = _spec_params(spec)
    except http.HttpError:
        pass  # task without a published spec: params unknown, passthrough still works
    meta["params"] = params
    return meta


def _spec_params(spec):
    defs = spec.get("$defs", {})
    props = spec.get("properties", {})
    ref = (props.get("parameters") or {}).get("$ref", "")
    if ref:  # task spec: {inputs, parameters:$ref}
        props = defs.get(ref.rsplit("/", 1)[-1], {}).get("properties", {})
    out = []
    for k, v in props.items():
        if k in ("inputs", "messages", "model", "stream", "stream_options"):
            continue
        if "$ref" in v:
            v = {**defs.get(v["$ref"].rsplit("/", 1)[-1], {}), **v}
        typ = v.get("type") or ("object" if "properties" in v else "any")
        if isinstance(typ, list):
            typ = "|".join(t for t in typ if t != "null")
        out.append({"name": k, "type": typ, "default": v.get("default", ""),
                    "description": " ".join((v.get("description") or "").split())[:160]})
    return out


# ---- run --------------------------------------------------------------------

def _client(cfg):
    try:
        from huggingface_hub import InferenceClient
        from huggingface_hub.inference import _client as hc
    except ImportError:
        raise UsageError("hf run needs huggingface_hub: python3 -m pip install --user huggingface_hub") from None
    # text_to_image/image_to_image decode to PIL; keep raw bytes instead (no Pillow dependency).
    if hasattr(hc, "_bytes_to_image"):
        hc._bytes_to_image = lambda b: b
    return InferenceClient(provider=cfg.get("hf_provider", "auto"), token=os.environ[ENV])


def _split_kwargs(fn, params):
    """Known kwargs go straight in; the rest ride in extra_body (provider passthrough)."""
    sig = inspect.signature(fn).parameters
    known = {k: v for k, v in params.items() if k in sig}
    extra = {k: v for k, v in params.items() if k not in sig}
    if extra:
        if "extra_body" in sig:
            known["extra_body"] = extra
        else:
            known.update(extra)  # let the client reject it verbatim
    return known


def run(model_id, task, inp, params, out, cfg):
    if not available():
        raise MissingToken(ENV, SIGNUP)
    method = CLIENT_METHOD.get(task)
    if not method:
        raise UsageError(f"hf: run does not support task {task} yet")
    client = _client(cfg)
    fn = getattr(client, method)
    try:
        if task in ("text-generation", "image-text-to-text"):
            msgs = [{"role": "user", "content": inp["text"]}]
            if inp.get("file"):
                raise UsageError("hf llm run takes text only; send files to an openrouter vision model")
            r = fn(messages=msgs, model=model_id, **_split_kwargs(fn, params))
            return {"text": r.choices[0].message.content}
        if task == "automatic-speech-recognition":
            if not inp.get("file"):
                raise UsageError("asr needs an audio file path as input")
            r = fn(inp["file"], model=model_id, **_split_kwargs(fn, params))
            return {"text": r.text}
        data = fn(inp["text"], model=model_id, **_split_kwargs(fn, params))
    except CliError:
        raise
    except Exception as e:  # HfHubHTTPError etc.: surface provider text verbatim
        raise CliError(f"hf: {_hf_error(e)}") from None
    if not isinstance(data, (bytes, bytearray)):  # PIL image if the patch point moved
        import io
        buf = io.BytesIO()
        data.save(buf, format="PNG")
        data = buf.getvalue()
    p = out_path(out, inp["text"], sniff_ext(data, DEFAULT_EXT.get(task, "bin")))
    Path(p).write_bytes(data)
    return {"path": str(p)}


def _hf_error(e):
    resp = getattr(e, "response", None)
    if resp is not None:
        try:
            return f"HTTP {resp.status_code}: {http._error_text(resp.text)}"
        except Exception:
            pass
    return str(e).strip()
