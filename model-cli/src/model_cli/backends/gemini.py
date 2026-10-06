"""Google Gemini API (AI Studio key, free tier): Interactions API for llm, vision, audio-in (asr) and tts."""
import base64
import mimetypes
import sys
from pathlib import Path

from .. import audio, http
from ..core import CliError
from .compat import ASR, LLM, TTS, VISION, Compat

GEN_KEYS = {"temperature", "top_p", "top_k", "max_output_tokens", "seed", "stop_sequences", "thinking_level",
            "speech_config", "candidate_count", "presence_penalty", "frequency_penalty"}
CHAT = [LLM, VISION, ASR]


class Gemini(Compat):
    NO_REASONING = {"thinking_level": "low"}

    def headers(self):
        return {"x-goog-api-key": self.token()}

    def live_ids(self):
        if self._live is None:
            self._live = []
            if self.available():
                try:
                    data = http.get_json(f"{self.base}/models?pageSize=200", headers=self.headers())
                    self._live = [m["name"].split("/", 1)[-1] for m in data.get("models", [])]
                except (http.HttpError, OSError, ValueError, KeyError) as e:
                    print(f"# gemini: live model list failed ({e}); curated list only", file=sys.stderr)
        return self._live

    def _row(self, m, task=None):
        row = super()._row(m, task)
        if not m.get("curated"):
            row["free"], row["price"] = "unknown", "check ai.google.dev/pricing"
        return row

    def lookup(self, model_id):
        row = super().lookup(model_id)
        row["is_free"] = row["free"] == "quota" or None
        return row

    # ---- Interactions API ---------------------------------------------------------------------------------
    @staticmethod
    def _body(model_id, parts, params):
        gen, top = {}, {}
        for k, v in params.items():
            if k == "max_tokens":
                gen["max_output_tokens"] = v
            elif k == "voice":
                gen["speech_config"] = [{"voice": v}]
            elif k in GEN_KEYS:
                gen[k] = v
            else:
                top[k] = v
        body = {"model": model_id, "input": parts, **top}
        if gen:
            body["generation_config"] = {**gen, **(top.get("generation_config") or {})}
        return body

    def _call(self, body):
        r = http.with_retry(lambda: http.post_json(f"{self.base}/interactions", body, headers=self.headers(),
                                                   timeout=600), retries=2, wait=4, backoff=2)
        if isinstance(r, dict) and r.get("error"):
            raise CliError(f"gemini: {r['error']}")
        out = []
        for step in r.get("steps") or []:
            if step.get("type") in (None, "model_output"):
                out += step.get("content") or []
        return out or (r.get("outputs") or [])

    @staticmethod
    def _part(path):
        mime = audio.MIME.get(Path(path).suffix.lstrip(".").lower()) or mimetypes.guess_type(str(path))[0] \
            or "application/octet-stream"
        kind = {"audio": "audio", "image": "image", "video": "video"}.get(mime.split("/")[0], "document")
        return {"type": kind, "data": base64.b64encode(Path(path).read_bytes()).decode(), "mime_type": mime}

    @staticmethod
    def _text(content):
        return "".join(c.get("text", "") for c in content if c.get("type") == "text").strip()

    def chat(self, model_id, inp, params):
        parts = [{"type": "text", "text": inp["text"]}]
        files = ([inp["file"]] if inp.get("file") else []) + (inp.get("refs") or [])
        parts += [self._part(f) for f in files]
        return {"text": self._text(self._call(self._body(model_id, parts, params))), "cost": 0}

    def asr(self, model_id, path, params, prompt=None):
        parts = [{"type": "text", "text": prompt or "Transcribe this audio verbatim."}, self._part(path)]
        return self._text(self._call(self._body(model_id, parts, params)))

    def tts(self, model_id, text, params):
        body = self._body(model_id, [{"type": "text", "text": text}], params)
        body.setdefault("response_format", {"type": "audio"})
        gc = body.setdefault("generation_config", {})
        gc.setdefault("speech_config", [{"voice": self.tts_voice}])
        for c in self._call(body):
            if c.get("type") == "audio" and c.get("data"):
                data = base64.b64decode(c["data"])
                return data if data[:4] == b"RIFF" else audio.pcm_to_wav(data)  # streaming-style raw L16 24 kHz
        raise CliError("gemini: no audio in the response")


backend = Gemini(
    "gemini", "GEMINI_API_KEY", "https://aistudio.google.com/apikey",
    "https://generativelanguage.googleapis.com/v1beta",
    [dict(m, curated=True) for m in [
        {"id": "gemini-3.5-flash", "tasks": CHAT},
        {"id": "gemini-3.8-flash", "tasks": CHAT},
        {"id": "gemini-3.5-flash-lite", "tasks": CHAT},
        {"id": "gemini-3.1-flash-lite", "tasks": CHAT},
        {"id": "gemini-2.5-pro", "tasks": [LLM, VISION]},
        {"id": "gemini-2.5-flash", "tasks": CHAT},
        {"id": "gemini-3.8-flash-tts", "tasks": [TTS]},
        {"id": "gemini-3.8-flash-lite-tts", "tasks": [TTS]},
    ]],
    asr_max=14 * 2**20, asr_formats=("wav", "mp3", "aiff", "aac", "ogg", "opus", "flac", "m4a", "webm"),
    tts_voice="Kore")
