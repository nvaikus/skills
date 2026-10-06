"""Media of stored messages -> files. Keys come from the store (normalize.media_of); a row stored without
them (before the store kept keys) cannot be downloaded - WhatsApp re-sends keys only in a new history sync."""
import mimetypes
import os
import re
import tempfile
from pathlib import Path

from ..core.errors import CliError, UsageError
from .normalize import MEDIA_KINDS
from .peers import iso_ts

FIELDS = ["date", "msg_id", "kind", "status", "path"]
DEFAULT_DIR = Path(tempfile.gettempdir()) / "wa-cli"
EXT = {"image/jpeg": ".jpg", "image/webp": ".webp", "video/mp4": ".mp4", "audio/ogg": ".ogg", "audio/mpeg": ".mp3",
       "audio/mp4": ".m4a", "application/pdf": ".pdf"}
NO_KEYS = ("no download keys stored: the message reached wa-cli before it kept media keys; WhatsApp sends keys again "
           "only in a new history sync (logout + login, the user's call)")


def safe_name(name):
    name = re.sub(r'[\x00-\x1f/\\:*?"<>|]', "_", os.path.basename(name or "")).strip(" .")
    return name[:200] or None


def file_name(m):
    """Original file name (documents), else <date>_<msg_id><ext from mimetype>."""
    name = safe_name(m["file"])
    if name:
        return name
    mime = (m["mime"] or "").split(";")[0].strip()
    ext = EXT.get(mime) or mimetypes.guess_extension(mime) or ""
    day = (iso_ts(m["ts"]) or "")[:10]
    return f"{day}_{m['id']}{ext}" if day else f"{m['id']}{ext}"


def pick(store, chat_jids, ids):
    """Explicit message ids -> rows; unknown id or non-media message -> exit 2."""
    out = []
    for mid in ids:
        m = store.message(chat_jids, mid)
        if not m:
            raise UsageError(f"no message {mid!r} in this chat in the local store - ids: wa-cli history CHAT")
        if m["kind"] not in MEDIA_KINDS:
            raise UsageError(f"message {mid} is {m['kind']}, not media ({', '.join(MEDIA_KINDS)}) - nothing to download")
        out.append(m)
    return out


def select(store, chat_jids, kinds=None, since=None, until=None, limit=50):
    kinds = list(kinds or MEDIA_KINDS)
    return store.messages(chat_jids, None, None, since, until, limit, kinds=kinds)


def _target(out_dir, name, taken):
    """Same name twice in one run -> 'name (2).ext'; an existing file from an earlier run is overwritten."""
    stem, ext = os.path.splitext(name)
    path, n = out_dir / name, 1
    while str(path) in taken:
        n += 1
        path = out_dir / f"{stem} ({n}){ext}"
    taken.add(str(path))
    return path


def download(session, rows, out_dir):
    """-> (result rows, {status: first error message}). Statuses: ok | no-keys | expired | failed."""
    out_dir = Path(out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    results, errors, taken = [], {}, set()
    for m in rows:
        r = {"date": iso_ts(m["ts"]), "msg_id": m["id"], "kind": m["kind"], "file": m["file"], "status": "ok",
             "path": None, "size": None, "error": None}
        if not m["media"]:
            r["status"], r["error"] = "no-keys", NO_KEYS
        else:
            path = _target(out_dir, file_name(m), taken)
            part = path.with_name(path.name + ".part")
            try:
                session.download(m["media"], str(part))
                os.replace(part, path)
                r["path"], r["size"] = str(path), path.stat().st_size
            except CliError as e:
                r["status"], r["error"] = getattr(e, "status", "failed"), str(e)
                if part.exists():
                    part.unlink()
        if r["error"]:
            errors.setdefault(r["status"], r["error"])
        results.append(r)
    return results, errors
