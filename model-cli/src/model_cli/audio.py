"""Audio prep for ASR backends: transcode + chunk to fit a provider's size/format limits (ffmpeg), PCM -> WAV."""
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

from . import core
from .core import UsageError

OPUS_BPS = 32000  # transcode target: Opus (or MP3) 32 kbit/s mono 16 kHz ~ 14 MB/hour, plenty for speech
MIME = {"wav": "audio/wav", "mp3": "audio/mpeg", "ogg": "audio/ogg", "opus": "audio/ogg", "oga": "audio/ogg",
        "flac": "audio/flac", "m4a": "audio/mp4", "mp4": "audio/mp4", "aac": "audio/aac", "webm": "audio/webm",
        "aiff": "audio/aiff", "aif": "audio/aiff", "mpeg": "audio/mpeg", "mpga": "audio/mpeg"}


def mime_of(path):
    return MIME.get(Path(path).suffix.lstrip(".").lower(), "application/octet-stream")


def _note(msg):
    print(f"# {msg}", file=sys.stderr)


def _ffmpeg(*args):
    exe = shutil.which("ffmpeg")
    if not exe:
        raise UsageError("this audio needs converting/splitting but ffmpeg is not on PATH - install ffmpeg "
                         "(brew install ffmpeg / apt install ffmpeg / winget install ffmpeg)")
    r = subprocess.run([exe, "-hide_banner", "-loglevel", "error", "-y", *args], capture_output=True, text=True)
    if r.returncode:
        raise UsageError(f"ffmpeg failed: {r.stderr.strip()[-500:]}")


def _mb(n):
    return f"{n / 2**20:.3g} MB"


def prepare(path, max_bytes, formats):
    """-> list of file paths, each <= max_bytes and in `formats` (ext set). Original file when it already fits."""
    p = Path(path)
    ext = p.suffix.lstrip(".").lower()
    size = p.stat().st_size
    if ext in formats and size <= max_bytes:
        return [str(p)]
    target = "ogg" if "ogg" in formats else "mp3" if "mp3" in formats else None
    if not target:
        raise UsageError(f"{p.name}: format/size not accepted by this backend ({', '.join(sorted(formats))}, "
                         f"<= {_mb(max_bytes)})")
    core.OUT_DIR.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="audio-", dir=core.OUT_DIR))
    seg = max(60, int(max_bytes * 0.9 * 8 / OPUS_BPS))  # seconds per chunk that fit the byte cap
    codec = ["libopus", "-b:a", str(OPUS_BPS)] if target == "ogg" else ["libmp3lame", "-b:a", str(OPUS_BPS)]
    whole = tmp / f"audio.{target}"
    _ffmpeg("-i", str(p), "-vn", "-ac", "1", "-ar", "16000", "-c:a", *codec, str(whole))
    if whole.stat().st_size <= max_bytes:
        _note(f"audio transcoded to {target} ({size // 1024} KB -> {whole.stat().st_size // 1024} KB)")
        return [str(whole)]
    _ffmpeg("-i", str(whole), "-f", "segment", "-segment_time", str(seg), "-c", "copy",
            str(tmp / f"part-%03d.{target}"))
    parts = sorted(str(x) for x in tmp.glob(f"part-*.{target}"))
    _note(f"audio split into {len(parts)} chunks of <= {seg // 60} min (backend cap {_mb(max_bytes)}); "
          "texts joined")
    return parts


def transcribe(path, max_bytes, formats, fn):
    """Run fn(chunk_path) -> text over prepared chunks; join with newlines."""
    parts = prepare(path, max_bytes, formats)
    try:
        return "\n".join(t.strip() for t in (fn(c) for c in parts) if t and t.strip())
    finally:
        tmp = Path(parts[0]).parent
        if tmp.parent == core.OUT_DIR and tmp.name.startswith("audio-"):
            shutil.rmtree(tmp, ignore_errors=True)


def pcm_to_wav(pcm, rate=24000, channels=1, width=2):
    hdr = b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt " + struct.pack(
        "<IHHIIHH", 16, 1, channels, rate, rate * channels * width, channels * width, width * 8) + b"data" + \
        struct.pack("<I", len(pcm))
    return hdr + pcm
