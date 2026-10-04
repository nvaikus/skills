"""Attachments -> local files; voice -> text via model-cli (optional dependency)."""
import json
import logging
import re
import shutil
import subprocess
import time
from pathlib import Path

from . import config

log = logging.getLogger("claude-tg")
STT_PROMPT = "Transcribe this audio verbatim in its original language. Output only the transcript."


class NoStt(Exception):
    """key = ui string for the owner (why.stt_missing / why.stt_failed); str(e) = detail for logs / verbose."""
    def __init__(self, detail: str, key: str = "stt_failed"):
        super().__init__(detail)
        self.key = key


def _safe(name: str) -> str:
    return re.sub(r"[^\w.\-]+", "_", name).strip("._")[:80] or "file"


def fetch(bot, msg: dict, folder: Path):
    """Download what the message carries. Returns (files, audio): files = paths to hand to claude,
    audio = path to transcribe (voice / audio / video note) or None."""
    mid = msg["message_id"]
    files, audio = [], None
    if msg.get("photo"):
        files.append(bot.download(msg["photo"][-1]["file_id"], folder / f"{mid}.jpg"))
    for key in ("document", "video", "animation"):
        if msg.get(key):
            obj = msg[key]
            name = obj.get("file_name") or f"{key}{Path(obj.get('mime_type', '/bin').split('/')[-1]).suffix or ''}"
            files.append(bot.download(obj["file_id"], folder / f"{mid}_{_safe(name)}"))
    for key, ext in (("voice", ".ogg"), ("audio", ""), ("video_note", ".mp4")):
        if msg.get(key):
            obj = msg[key]
            name = obj.get("file_name") or f"{key}{ext}"
            audio = bot.download(obj["file_id"], folder / f"{mid}_{_safe(name)}")
    return files, audio


def transcribe(path: Path, cfg: dict, env: dict) -> str:
    cli = config.model_cli_bin()
    if not cli:
        raise NoStt("model-cli not found", "stt_missing")
    src = path
    if shutil.which("ffmpeg"):  # chat-audio models reject ogg/opus; mp3 16 kHz mono works everywhere
        src = path.with_suffix(".stt.mp3")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000",
                        str(src)], check=True, timeout=120)
    errors = []
    for model in cfg["stt_models"]:
        argv = [*cli, "asr", str(src)]
        if model:
            argv += ["-m", model]
        if model.startswith("openrouter:"):
            argv += ["--prompt", STT_PROMPT, "--no-reasoning"]
        if cfg.get("stt_paid"):
            argv.append("--paid")
        for attempt in range(2):
            r = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=300)
            if r.returncode == 0:
                try:
                    text = json.loads(r.stdout.strip().splitlines()[-1]).get("text", "").strip()
                except (ValueError, IndexError):
                    text = ""
                if text:
                    return text
            err = (r.stderr.strip().splitlines() or ["no output"])[-1][:200]
            errors.append(f"{model or 'default'}: {err}")
            log.warning("stt failed: %s", errors[-1])
            if r.returncode in (2, 3):  # missing token / paid refused: retry is pointless
                break
            time.sleep(3)
    raise NoStt("transcription failed: " + "; ".join(errors[-2:]))
