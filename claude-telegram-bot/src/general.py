"""A group's General topic while it is ignored (config group_general false): a mention of the bot opens a topic.

`mentions` decides whether a General message addresses the bot; `Buffer` keeps the last N General messages per
chat (only senders the bot would accept) so the new topic's first prompt carries what was said before. The Bot API
has no history fetch: the buffer is the only source. Persisted in STATE_DIR/general.json (text only, bounded)."""
import json
import os
import threading
import time
from pathlib import Path

TEXT_MAX = 1000  # chars kept per buffered message
CONTEXT_OPEN = "[Recent messages in the group's General topic, oldest first - context only, not addressed to you:]"
CONTEXT_CLOSE = "[End of General context. The message that mentioned you:]"
MEDIA = (("photo", "photo"), ("video", "video"), ("animation", "GIF"), ("video_note", "video note"),
         ("voice", "voice note"), ("audio", "audio"), ("document", "file"), ("sticker", "sticker"),
         ("location", "location"), ("venue", "venue"), ("contact", "contact"), ("poll", "poll"))


def _slice(text: str, off: int, length: int) -> str:
    """Entity offsets count UTF-16 code units."""
    b = text.encode("utf-16-le")
    return b[off * 2:(off + length) * 2].decode("utf-16-le", "replace")


def mentions(msg: dict, username, bot_id) -> bool:
    """The message addresses the bot: an @username mention entity, a /cmd@username command, a text_mention of the
    bot, or a reply to one of the bot's own messages."""
    rt = (msg.get("reply_to_message") or {}).get("from") or {}
    if bot_id and rt.get("id") == bot_id:
        return True
    for field, ents in (("text", "entities"), ("caption", "caption_entities")):
        text = msg.get(field) or ""
        for e in msg.get(ents) or []:
            if e.get("type") == "text_mention" and bot_id and (e.get("user") or {}).get("id") == bot_id:
                return True
            if e.get("type") not in ("mention", "bot_command") or not username:
                continue
            part = _slice(text, e.get("offset", 0), e.get("length", 0)).lower()
            if part == "@" + username.lower() if e["type"] == "mention" else part.endswith("@" + username.lower()):
                return True
    return False


def strip_mention(text: str, username) -> str:
    """Text without the bot's @username (topic title seed)."""
    if username:
        low, tag = text.lower(), "@" + username.lower()
        while tag in low:
            i = low.index(tag)
            text, low = text[:i] + text[i + len(tag):], low[:i] + low[i + len(tag):]
    return " ".join(text.split())


def entry(msg: dict) -> dict:
    """Buffered form of a message: sender name, unix time, text (media as a short placeholder)."""
    f = msg.get("from") or {}
    name = " ".join(x for x in (f.get("first_name"), f.get("last_name")) if x) or "?"
    if f.get("username"):
        name += f" (@{f['username']})"
    kind = next((label for key, label in MEDIA if key in msg), None)
    if kind == "file":
        kind += " " + ((msg.get("document") or {}).get("file_name") or "")
    elif kind == "sticker":
        kind += " " + ((msg.get("sticker") or {}).get("emoji") or "")
    text = (msg.get("text") or msg.get("caption") or "").strip()
    if kind:
        text = f"[{kind.strip()}]" + (" " + text if text else "")
    return {"from": name, "date": int(msg.get("date") or 0), "text": text[:TEXT_MAX]}


def render(entries: list) -> str:
    """The context block for the first prompt of the new topic; '' when there is nothing."""
    if not entries:
        return ""
    lines = [f"[{time.strftime('%Y-%m-%d %H:%M', time.localtime(e['date']))}] {e['from']}: {e['text']}"
             for e in entries]
    return "\n".join([CONTEXT_OPEN, *lines, CONTEXT_CLOSE])


def title_part(prompt: str) -> str:
    """The prompt without the General context (the auto-title must name the request, not the chatter)."""
    return prompt.partition(CONTEXT_CLOSE)[2].strip() if CONTEXT_CLOSE in prompt else prompt


class Buffer:
    """chat id -> last `size` entries, oldest first; saved on every change (atomic replace)."""

    def __init__(self, path: Path, size: int):
        self.path, self.size, self.lock = path, max(0, int(size or 0)), threading.Lock()
        self.data = {}
        try:
            raw = json.loads(path.read_text())
            self.data = {str(k): list(v)[-self.size:] if self.size else [] for k, v in raw.items()
                         if isinstance(v, list)}
        except (OSError, ValueError, AttributeError):
            pass

    def add(self, chat, msg: dict):
        if not self.size:
            return
        e = entry(msg)
        if not e["text"]:
            return
        with self.lock:
            items = self.data.setdefault(str(chat), [])
            items.append(e)
            del items[:-self.size]
            self._save()

    def recent(self, chat) -> list:
        with self.lock:
            return list(self.data.get(str(chat), []))

    def _save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False))
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
        except OSError:
            pass
