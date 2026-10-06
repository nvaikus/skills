"""Attachments -> local files; voice -> text via model-cli (optional dependency)."""
import json
import logging
import re
import shutil
import subprocess
import time
from pathlib import Path

from . import config
from .botapi import TgError

log = logging.getLogger("claude-tg")
STT_PROMPT = "Transcribe this audio verbatim in its original language. Output only the transcript."


class NoStt(Exception):
    """key = ui string for the owner (why.stt_missing / why.stt_failed); str(e) = detail for logs / verbose."""
    def __init__(self, detail: str, key: str = "stt_failed"):
        super().__init__(detail)
        self.key = key


def _safe(name: str) -> str:
    return re.sub(r"[^\w.\-]+", "_", name).strip("._")[:80] or "file"


CLOUD_LIMIT = 20 << 20  # Bot API getFile limit on api.telegram.org; a local server (--local) takes up to 2 GB
LOCAL_TIMEOUT = 1800     # a local server downloads the whole file inside getFile


class Skipped:
    """An attachment that could not be fetched. reason: too_big | local_down | failed; detail = log text."""
    def __init__(self, mid, kind, name, mime, size, reason, detail=""):
        self.mid, self.kind, self.name, self.mime, self.size = mid, kind, name, mime, size
        self.reason, self.detail = reason, detail

    def note(self) -> str:
        """Line for claude: it must know the attachment exists even though it is not on disk."""
        why = {"too_big": "larger than 20 MB - the Telegram Bot API cannot download it",
               "local_down": "larger than 20 MB and the local Bot API server is unreachable",
               }.get(self.reason, f"download failed ({self.detail})")
        return (f"[Attachment NOT downloaded: {self.name} - {self.kind}"
                f"{f' ({self.mime})' if self.mime else ''}, {mb(self.size)}, Telegram message {self.mid} in this "
                f"bot chat. Reason: {why}. The file is not on disk; the user was told why.]")


def mb(size) -> str:
    return f"{size / (1 << 20):.1f} MB" if size else "size unknown"


def _too_big(e) -> bool:
    return "too big" in (getattr(e, "description", "") or "").lower()


def _get(bot, big, obj, dest, kind, name, mid):
    """Path, or Skipped. Small files: cloud. > 20 MB (by file_size, or the cloud says 'file is too big'):
    the local Bot API server when configured, else Skipped('too_big')."""
    size = obj.get("file_size") or 0
    skip = lambda reason, detail="": Skipped(mid, kind, name, obj.get("mime_type"), size, reason, detail)  # noqa: E731
    if size <= CLOUD_LIMIT:
        try:
            return bot.download(obj["file_id"], dest)
        except TgError as e:
            if not _too_big(e):
                return skip("failed", e.description)
    if not big:
        return skip("too_big", "file is too big for the cloud Bot API; local_api_url not set")
    try:
        return big.download(obj["file_id"], dest, timeout=LOCAL_TIMEOUT)
    except TgError as e:
        if e.code == 0 and e.description.startswith("network"):
            return skip("local_down", e.description)
        return skip("failed", f"local Bot API: {e.description}")


def fetch(bot, msg: dict, folder: Path, big=None):
    """Download what the message carries. Returns (files, audio, skipped): files = paths to hand to claude,
    audio = path to transcribe (voice / audio / video note) or None, skipped = [Skipped] (never raises for
    a single attachment). big = Bot on a local Bot API server for files > 20 MB, or None."""
    mid = msg["message_id"]
    files, audio, skipped = [], None, []

    def take(obj, kind, name, fname):
        r = _get(bot, big, obj, folder / fname, kind, name, mid)
        if isinstance(r, Skipped):
            skipped.append(r)
            log.warning("message %s: %s %s (%s) not downloaded: %s - %s", mid, kind, r.name, mb(r.size),
                        r.reason, r.detail)
            return None
        return r

    if msg.get("photo"):
        got = take(msg["photo"][-1], "photo", "photo.jpg", f"{mid}.jpg")
        if got:
            files.append(got)
    for key in ("document", "video", "animation"):
        if msg.get(key):
            obj = msg[key]
            name = obj.get("file_name") or f"{key}{Path(obj.get('mime_type', '/bin').split('/')[-1]).suffix or ''}"
            got = take(obj, key, name, f"{mid}_{_safe(name)}")
            if got:
                files.append(got)
    for key, ext in (("voice", ".ogg"), ("audio", ""), ("video_note", ".mp4")):
        if msg.get(key):
            obj = msg[key]
            name = obj.get("file_name") or f"{key}{ext}"
            audio = take(obj, key, name, f"{mid}_{_safe(name)}") or audio
    return files, audio, skipped


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
