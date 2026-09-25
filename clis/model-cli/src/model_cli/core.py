"""Shared types: errors with exit codes, task vocabulary, config, output paths."""
import json
import os
import re
import time
from pathlib import Path

# ---- errors -> exit codes (house contract) --------------------------------


class CliError(Exception):
    code = 1


class UsageError(CliError):
    code = 2


class GuardRefused(CliError):
    code = 3


class MissingToken(UsageError):
    def __init__(self, env, signup):
        super().__init__(f"{env} is not set - get a free token at {signup} and export {env}=...")


# ---- tasks ----------------------------------------------------------------
# Short names -> canonical HF pipeline tags. Any other HF pipeline tag passes through.
TASKS = {
    "image": "text-to-image",
    "image-edit": "image-to-image",
    "video": "text-to-video",
    "tts": "text-to-speech",
    "asr": "automatic-speech-recognition",
    "audio": "text-to-audio",
    "llm": "text-generation",
    "vision": "image-text-to-text",
}
SHORT = {v: k for k, v in TASKS.items()}
# Tasks `run` can execute; value = output kind.
RUNNABLE = {
    "text-to-image": "file",
    "text-to-video": "file",
    "text-to-speech": "file",
    "text-to-audio": "file",
    "automatic-speech-recognition": "text",
    "text-generation": "text",
    "image-text-to-text": "text",
}


def canon_task(t):
    if not t:
        return None
    return TASKS.get(t, t)


def short_task(t):
    return SHORT.get(t, t)


# ---- config ---------------------------------------------------------------
CONFIG_PATH = Path(os.environ.get("MODEL_CLI_CONFIG", "~/.claude/model-cli/config.json")).expanduser()
OUT_DIR = Path(os.environ.get("MODEL_CLI_OUT", "/tmp/model-cli"))

DEFAULT_CONFIG = {
    "free_only": True,
    "hf_provider": "auto",
    "defaults": {
        "image": ["hf:black-forest-labs/FLUX.1-schnell", "pollinations:default"],
        "video": ["hf:Wan-AI/Wan2.2-TI2V-5B"],
        "tts": ["hf:hexgrad/Kokoro-82M", "pollinations:tts"],
        "asr": ["hf:openai/whisper-large-v3"],
        "llm": ["openrouter:openrouter/free", "pollinations:default"],
    },
    "aliases": {
        "flux": "hf:black-forest-labs/FLUX.1-schnell",
        "kokoro": "hf:hexgrad/Kokoro-82M",
        "whisper": "hf:openai/whisper-large-v3",
        "free-llm": "openrouter:openrouter/free",
    },
}


def load_config():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if CONFIG_PATH.exists():
        try:
            user = json.loads(CONFIG_PATH.read_text())
        except ValueError as e:
            raise UsageError(f"bad JSON in {CONFIG_PATH}: {e}") from None
        for k, v in user.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    return cfg


# ---- output paths ---------------------------------------------------------

def out_path(explicit, prompt, ext):
    """Explicit -o wins (dir -> file inside it); else throwaway file under OUT_DIR."""
    if explicit:
        p = Path(explicit).expanduser()
        if p.is_dir() or explicit.endswith(("/", os.sep)):
            p.mkdir(parents=True, exist_ok=True)
            p = p / _name(prompt, ext)
        elif not p.suffix:
            p = p.with_suffix("." + ext)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUT_DIR / _name(prompt, ext)


def _name(prompt, ext):
    slug = re.sub(r"[^a-z0-9]+", "-", str(prompt or "out").lower()).strip("-")[:40] or "out"
    return f"{time.strftime('%Y%m%d-%H%M%S')}-{slug}.{ext}"


MAGIC = [
    (b"\x89PNG", "png"), (b"\xff\xd8\xff", "jpg"), (b"GIF8", "gif"), (b"RIFF", None),
    (b"ID3", "mp3"), (b"\xff\xfb", "mp3"), (b"\xff\xf3", "mp3"), (b"fLaC", "flac"), (b"OggS", "ogg"),
    (b"\x1aE\xdf\xa3", "webm"),
]


def sniff_ext(data, fallback):
    for sig, ext in MAGIC:
        if data.startswith(sig):
            if sig == b"RIFF":
                return {b"WEBP": "webp", b"WAVE": "wav"}.get(data[8:12], fallback)
            return ext
    if data[4:8] == b"ftyp":
        return "mp4"
    return fallback
