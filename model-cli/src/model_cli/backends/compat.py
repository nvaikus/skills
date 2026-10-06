"""OpenAI-compatible free-tier backends (Groq, Mistral; Cloudflare subclasses it).

A backend is an instance exposing the module interface cli uses: NAME ENV SIGNUP, available, search, lookup,
info, run (+ optional ENVS, no_reasoning). Catalog = curated free models (keyless) + the live /models list when a
token is set; any other id is passed through and the provider's error comes back verbatim."""
import json
import os
import sys
from pathlib import Path

from .. import audio, http
from ..core import CliError, MissingToken, UsageError, file_part, out_path, short_task, sniff_ext

ASR, TTS, LLM, VISION = "automatic-speech-recognition", "text-to-speech", "text-generation", "image-text-to-text"
IMAGE = "text-to-image"
PARAMS = {
    LLM: ["temperature", "max_tokens", "top_p", "seed", "stop", "response_format", "reasoning_effort"],
    VISION: ["temperature", "max_tokens", "top_p"],
    ASR: ["language", "prompt", "temperature"],
    TTS: ["voice", "response_format", "speed"],
}


def guess_tasks(model_id):
    m = model_id.lower()
    if any(w in m for w in ("whisper", "voxtral", "transcribe", "nova-")):
        return [ASR]
    if any(w in m for w in ("tts", "orpheus", "melotts", "aura", "speech")):
        return [TTS]
    if any(w in m for w in ("flux", "stable-diffusion", "dreamshaper", "phoenix", "lucid")):
        return [IMAGE]
    if any(w in m for w in ("guard", "embed", "rerank", "moderation")):
        return []
    return [LLM]


class Compat:
    ENVS = None
    NO_REASONING = None  # params merged by --no-reasoning; None -> flag ignored with a note

    def __init__(self, name, env, signup, base, models, *, asr_max=0, asr_formats=(), tts_voice=None,
                 tts_format="wav"):
        self.NAME, self.ENV, self.SIGNUP, self.base = name, env, signup, base
        self.models = models  # [{"id", "tasks": [...]}]
        self.asr_max, self.asr_formats = asr_max, set(asr_formats)
        self.tts_voice, self.tts_format = tts_voice, tts_format
        self._live = None

    # ---- auth -----------------------------------------------------------------
    def token(self):
        return os.environ.get(self.ENV)

    def available(self, task=None):
        return bool(self.token()) and (task is None or task in self.tasks())

    def tasks(self):
        return {t for m in self.models for t in m["tasks"]}

    def headers(self):
        return {"Authorization": f"Bearer {self.token()}"}

    def need_token(self):
        if not self.available():
            missing = [e for e in (self.ENVS or [self.ENV]) if not os.environ.get(e)] or [self.ENV]
            raise MissingToken(" and ".join(missing), self.SIGNUP, hint=f"model-cli setup {self.NAME}")

    # ---- catalog ----------------------------------------------------------------
    def live_ids(self):
        if self._live is None:
            self._live = []
            if self.available():
                try:
                    data = http.get_json(f"{self.base}/models", headers=self.headers())
                    self._live = [m["id"] for m in data.get("data", data if isinstance(data, list) else [])
                                  if m.get("active", True) is not False]
                except (http.HttpError, OSError, ValueError, KeyError, TypeError) as e:
                    print(f"# {self.NAME}: live model list failed ({e}); curated list only", file=sys.stderr)
        return self._live

    def catalog(self):
        cur = {m["id"]: m for m in self.models}
        out = list(self.models)
        out += [{"id": i, "tasks": guess_tasks(i)} for i in self.live_ids() if i not in cur]
        return out

    def _row(self, m, task=None):
        tasks = m["tasks"] or [""]
        t = task if task in tasks else tasks[0]
        return {"id": f"{self.NAME}:{m['id']}", "backend": self.NAME, "task": short_task(t),
                "free": "quota", "price": "0 (free tier)", "popularity": "-", "providers": ""}

    def search(self, query, task, free, limit):
        words = (query or "").lower().split()
        rows = []
        for m in self.catalog():
            if task and task not in m["tasks"]:
                continue
            if not m["tasks"] and not words:
                continue
            if all(w in m["id"].lower() for w in words):
                rows.append(self._row(m, task))
        return rows[:limit]

    def lookup(self, model_id):  # no network: curated entry, else task guessed from the id
        m = next((x for x in self.models if x["id"] == model_id), None) or \
            {"id": model_id, "tasks": guess_tasks(model_id)}
        row = self._row(m)
        row["task_full"] = m["tasks"][0] if m["tasks"] else ""
        row["is_free"] = True
        return row

    def info(self, model_id):
        meta = self.lookup(model_id)
        names = PARAMS.get(meta["task_full"], [])
        meta["params"] = [{"name": n, "type": "", "default": "", "description": ""} for n in names]
        if meta["task_full"] == TTS and self.tts_voice:
            meta["default_voice"] = self.tts_voice
        return meta

    # ---- run ------------------------------------------------------------------
    def no_reasoning(self, model_id, params):
        if self.NO_REASONING is None:
            return False
        for k, v in self.NO_REASONING.items():
            params.setdefault(k, v)
        return True

    def chat_url(self):
        return f"{self.base}/chat/completions"

    def takes_refs(self, task):
        return task in (LLM, VISION)

    def run(self, model_id, task, inp, params, out, cfg):
        self.need_token()
        try:
            if task in (LLM, VISION):
                return self.chat(model_id, inp, params)
            if task == ASR:
                if not inp.get("file"):
                    raise UsageError("asr needs an audio file path as input")
                text = audio.transcribe(inp["file"], self.asr_max, self.asr_formats,
                                        lambda p: self.asr(model_id, p, params, inp.get("text")))
                return {"text": text, "cost": 0}
            if task == TTS:
                data = self.tts(model_id, inp["text"], params)
                return self.save(data, out, inp["text"], "wav")
            if task == IMAGE:
                data = self.image(model_id, inp["text"], params)
                return self.save(data, out, inp["text"], "jpg")
        except http.HttpError as e:
            raise CliError(f"{self.NAME}: HTTP {e.status}: {e.body}") from None
        raise UsageError(f"{self.NAME}: task {short_task(task)} not supported")

    def save(self, data, out, prompt, ext):
        p = out_path(out, prompt, sniff_ext(data, ext))
        Path(p).write_bytes(data)
        return {"path": str(p), "cost": 0}

    def chat(self, model_id, inp, params):
        content = inp["text"]
        files = ([inp["file"]] if inp.get("file") else []) + (inp.get("refs") or [])
        if files:
            content = [{"type": "text", "text": inp["text"]}] + [file_part(f) for f in files]
        payload = {"model": model_id, "messages": [{"role": "user", "content": content}], **params}
        r = http.with_retry(lambda: http.post_json(self.chat_url(), payload, headers=self.headers()),
                            retries=2, wait=4, backoff=2)
        if r.get("error"):
            raise CliError(f"{self.NAME}: {r['error']}")
        choice = r["choices"][0]
        text = choice["message"].get("content") or ""
        if not text and choice.get("finish_reason") == "length":
            print("# empty text: max_tokens ran out (reasoning ate it?) - raise --max-tokens or pass --no-reasoning",
                  file=sys.stderr)
        res = {"text": text, "cost": 0}
        if r.get("model") and r["model"] != model_id:
            res["served_by"] = r["model"]
        return res

    def asr(self, model_id, path, params, prompt=None):
        fields = {"model": model_id, **params}
        body, ctype = http.multipart(fields, {"file": (Path(path).name, Path(path).read_bytes(),
                                                       audio.mime_of(path))})
        hdrs = {**self.headers(), "Content-Type": ctype}
        _, _, raw = http.with_retry(lambda: http.request("POST", f"{self.base}/audio/transcriptions", headers=hdrs,
                                                         body=body, timeout=600), retries=2, wait=4, backoff=2)
        return json.loads(raw).get("text", "")

    def tts(self, model_id, text, params):
        payload = {"model": model_id, "input": text, "response_format": self.tts_format, **params}
        if self.tts_voice:
            payload.setdefault("voice", self.tts_voice)
        return http.request("POST", f"{self.base}/audio/speech", headers=self.headers(), body=payload,
                            timeout=300)[2]

    def image(self, model_id, prompt, params):
        raise UsageError(f"{self.NAME}: image generation not supported")


# ---- instances ----------------------------------------------------------------------------------------------

class Groq(Compat):
    def no_reasoning(self, model_id, params):
        if "gpt-oss" in model_id:
            params.setdefault("reasoning_effort", "low")  # gpt-oss cannot switch thinking fully off
            return True
        if "qwen" in model_id:
            params.setdefault("reasoning_effort", "none")
            return True
        return False


groq = Groq(
    "groq", "GROQ_API_KEY", "https://console.groq.com/keys", "https://api.groq.com/openai/v1",
    [{"id": "whisper-large-v3-turbo", "tasks": [ASR]},
     {"id": "whisper-large-v3", "tasks": [ASR]},
     {"id": "openai/gpt-oss-120b", "tasks": [LLM]},
     {"id": "openai/gpt-oss-20b", "tasks": [LLM]},
     {"id": "llama-3.3-70b-versatile", "tasks": [LLM]},
     {"id": "llama-3.1-8b-instant", "tasks": [LLM]},
     {"id": "qwen/qwen3.8-27b", "tasks": [LLM]},
     {"id": "canopylabs/orpheus-v1-english", "tasks": [TTS]},
     {"id": "canopylabs/orpheus-arabic-saudi", "tasks": [TTS]}],
    asr_max=24 * 2**20, asr_formats=("flac", "mp3", "mp4", "mpeg", "mpga", "m4a", "ogg", "opus", "wav", "webm"),
    tts_voice="hannah")

mistral = Compat(
    "mistral", "MISTRAL_API_KEY", "https://console.mistral.ai/api-keys", "https://api.mistral.ai/v1",
    [{"id": "mistral-small-latest", "tasks": [LLM, VISION]},
     {"id": "mistral-medium-latest", "tasks": [LLM, VISION]},
     {"id": "mistral-large-latest", "tasks": [LLM]},
     {"id": "magistral-medium-latest", "tasks": [LLM]},
     {"id": "codestral-latest", "tasks": [LLM]},
     {"id": "voxtral-mini-latest", "tasks": [ASR]}],
    asr_max=24 * 2**20, asr_formats=("flac", "mp3", "mp4", "m4a", "ogg", "opus", "wav", "webm"))
