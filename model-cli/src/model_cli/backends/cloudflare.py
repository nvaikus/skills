"""Cloudflare Workers AI: 10k neurons/day free. Chat via the OpenAI-compatible /ai/v1; asr/image/tts via /ai/run."""
import base64
import json
import os

from .. import audio, http
from ..core import CliError
from .compat import ASR, IMAGE, LLM, TTS, VISION, Compat


class Cloudflare(Compat):
    ACCOUNT_ENV = "CLOUDFLARE_ACCOUNT_ID"

    @property
    def ENVS(self):
        return [self.ENV, self.ACCOUNT_ENV]

    def available(self, task=None):
        return bool(os.environ.get(self.ACCOUNT_ENV)) and super().available(task)

    @property
    def base(self):
        return f"https://api.cloudflare.com/client/v4/accounts/{os.environ.get(self.ACCOUNT_ENV, '-')}/ai"

    @base.setter
    def base(self, _):
        pass

    def live_ids(self):
        return []  # catalog search needs auth + paging; curated list, any @cf/... id passes through

    def chat_url(self):
        return f"{self.base}/v1/chat/completions"

    def _run(self, model_id, payload=None, raw=None, ctype=None):
        hdrs = self.headers()
        if raw is not None:
            hdrs["Content-Type"] = ctype or "application/octet-stream"
        _, h, data = http.with_retry(
            lambda: http.request("POST", f"{self.base}/run/{model_id}", headers=hdrs,
                                 body=raw if raw is not None else payload, timeout=300), retries=1, wait=4)
        if "json" not in (h.get("Content-Type") or h.get("content-type") or ""):
            return data  # binary model output (png / mp3)
        j = json.loads(data)
        if not j.get("success", True):
            raise CliError(f"cloudflare: {http._error_text(data.decode('utf-8', 'replace'))}")
        return j.get("result", j)

    def asr(self, model_id, path, params, prompt=None):
        blob = open(path, "rb").read()
        if "turbo" in model_id or "nova" in model_id:
            r = self._run(model_id, {"audio": base64.b64encode(blob).decode(), **params})
        else:  # @cf/openai/whisper, whisper-tiny-en: raw bytes body
            r = self._run(model_id, raw=blob, ctype=audio.mime_of(path))
        return r.get("text", "") if isinstance(r, dict) else ""

    def tts(self, model_id, text, params):
        key = "prompt" if "melotts" in model_id else "text"
        r = self._run(model_id, {key: text, **params})
        return base64.b64decode(r["audio"]) if isinstance(r, dict) else r

    def image(self, model_id, prompt, params):
        r = self._run(model_id, {"prompt": prompt, **params})
        return base64.b64decode(r["image"]) if isinstance(r, dict) else r


backend = Cloudflare(
    "cloudflare", "CLOUDFLARE_API_TOKEN", "https://dash.cloudflare.com/profile/api-tokens", None,
    [{"id": "@cf/openai/whisper-large-v3-turbo", "tasks": [ASR]},
     {"id": "@cf/openai/whisper", "tasks": [ASR]},
     {"id": "@cf/black-forest-labs/flux-1-schnell", "tasks": [IMAGE]},
     {"id": "@cf/myshell-ai/melotts", "tasks": [TTS]},
     {"id": "@cf/openai/gpt-oss-120b", "tasks": [LLM]},
     {"id": "@cf/meta/llama-3.3-70b-instruct-fp8-fast", "tasks": [LLM]},
     {"id": "@cf/meta/llama-4-scout-17b-16e-instruct", "tasks": [LLM, VISION]}],
    asr_max=15 * 2**20, asr_formats=("mp3", "wav", "ogg", "opus", "flac", "m4a", "webm"))
