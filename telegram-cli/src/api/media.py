"""Media vocabulary: kind of a message's media, its file name, listing and downloading. Read-only."""
import os
import re

from ..core import tg
from ..core.errors import UsageError
from ..core.timeparse import iso

# Checked in this order: voice is audio, round/gif are video, sticker is a document.
KINDS = ["voice", "round", "gif", "sticker", "audio", "video", "photo", "document"]
_ATTR = {"round": "video_note"}
GET_FIELDS = ["msg_id", "date", "type", "size", "path"]
LIST_FIELDS = ["msg_id", "date", "type", "size", "name"]


def kind(m):
    """'document' | 'photo' | 'video' | 'voice' | 'audio' | 'round' | 'gif' | 'sticker' (downloadable),
    another lowercase label for geo/poll/contact/..., None for no media or a link preview."""
    media = getattr(m, "media", None)
    if media is None or type(media).__name__ == "MessageMediaWebPage":
        return None
    for k in KINDS:
        if getattr(m, _ATTR.get(k, k), None):
            return k
    return type(media).__name__.replace("MessageMedia", "").lower()


def file_info(m):
    """(original name or None, size or None, ext) of a downloadable media."""
    f = getattr(m, "file", None)
    if f is None:
        return None, None, ""
    return getattr(f, "name", None), getattr(f, "size", None), getattr(f, "ext", None) or ""


def safe_name(name):
    """A sender-chosen file name, reduced to one plain path component."""
    name = re.sub(r"[\x00-\x1f/\\:]", "_", name or "").strip().lstrip(".")
    return name[:200] or None


def file_name(m, k):
    name, _, ext = file_info(m)
    return safe_name(name) or f"{k}_{m.id}{ext}"


def row(m, k):
    name, size, _ = file_info(m)
    return {"msg_id": m.id, "date": iso(m.date), "type": k, "size": size, "name": file_name(m, k),
            "orig_name": name, "path": None}


def by_ids(client, chat, ids):
    """Messages by id; every one must exist and carry downloadable media, else exit 2 before any download."""
    got = client.get_messages(chat, ids=list(ids))
    got = got if isinstance(got, list) else [got]
    out, bad = [], []
    for i, m in zip(ids, got):
        k = kind(m) if m is not None else None
        if m is None:
            bad.append(f"{i}: no such message in this chat")
        elif k not in KINDS:
            bad.append(f"{i}: no downloadable media ({k or 'text only'})")
        else:
            out.append((m, k))
    if bad:
        raise UsageError("nothing downloaded - " + "; ".join(bad))
    return out


def scan(client, chat, kinds=None, since=None, until=None, limit=50, sender=None):
    """Newest first: messages with downloadable media of the given kinds in [since, until]. -> (pairs, more)."""
    flt = tg.media_filter(kinds[0]) if kinds and len(kinds) == 1 else None
    out = []
    for m in client.iter_messages(chat, offset_date=until, filter=flt, from_user=sender):
        if since and m.date < since:
            return out, False
        k = kind(m)
        if k in KINDS and (not kinds or k in kinds):
            if len(out) >= limit:
                return out, True
            out.append((m, k))
    return out, False


def download(client, pairs, out_dir):
    """Write each media into out_dir under its original name; a name repeated in this run gets _<msg_id>.
    An existing file is overwritten (reruns are idempotent). -> rows with path."""
    os.makedirs(out_dir, exist_ok=True)
    used, rows = set(), []
    for m, k in pairs:
        r = row(m, k)
        name = r["name"]
        if name in used:
            stem, ext = os.path.splitext(name)
            name = f"{stem}_{m.id}{ext}"
        used.add(name)
        r["path"] = client.download_media(m, file=os.path.join(out_dir, name))
        rows.append(r)
    return rows
