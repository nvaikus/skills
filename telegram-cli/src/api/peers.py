"""Peer vocabulary: entity kind/name/id, dialogs, people search, resolving a chat reference."""
import re
import time
from datetime import datetime, timezone

from ..core import tg
from ..core.errors import UsageError
from ..core.timeparse import iso

PEER_FIELDS = ["id", "type", "name", "username"]
USERNAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{3,31}")
LINK_RE = re.compile(r"(?:https?://)?(?:t\.me|telegram\.me)/([A-Za-z][A-Za-z0-9_]{3,31})/?$")
SELF = ("me", "self", "saved")
MAX_CANDIDATES = 10


# ---- entity vocabulary (duck-typed on Telethon class names) ------------------

def kind(e):
    name = type(e).__name__
    if name == "User":
        return "bot" if getattr(e, "bot", False) else "user"
    if name in ("Chat", "ChatForbidden"):
        return "group"
    if name in ("Channel", "ChannelForbidden"):
        return "group" if getattr(e, "megagroup", False) else "channel"
    return name.lower()


def name(e):
    if type(e).__name__ == "User":
        full = " ".join(p for p in (getattr(e, "first_name", None), getattr(e, "last_name", None)) if p)
        return full or ("Deleted Account" if getattr(e, "deleted", False) else None)
    return getattr(e, "title", None)


def username(e):
    if getattr(e, "username", None):
        return e.username
    for u in getattr(e, "usernames", None) or []:  # collectible / multiple usernames
        if getattr(u, "active", False):
            return u.username
    return None


def peer_id(e):
    """Marked id, the form `get_entity` accepts back: user N, basic group -N, channel/supergroup -100N."""
    k = type(e).__name__
    if k in ("Chat", "ChatForbidden"):
        return -e.id
    if k in ("Channel", "ChannelForbidden"):
        return int(f"-100{e.id}")
    return e.id


def peer_key(p):
    """TL Peer (PeerUser/PeerChat/PeerChannel) -> marked id."""
    if hasattr(p, "channel_id"):
        return int(f"-100{p.channel_id}")
    if hasattr(p, "chat_id"):
        return -p.chat_id
    return p.user_id


def row(e, **extra):
    r = {"id": peer_id(e), "type": kind(e), "name": name(e), "username": username(e)}
    r.update(extra)
    return r


def link(e, msg_id):
    if e is None:
        return None
    if username(e):
        return f"https://t.me/{username(e)}/{msg_id}"
    if type(e).__name__ == "Channel":
        return f"https://t.me/c/{e.id}/{msg_id}"
    return None


def _text(e):
    return " ".join(filter(None, (name(e), username(e)))).casefold()


# ---- dialogs ------------------------------------------------------------------

def folders(client):
    """Marked peer id -> [chat-folder titles] it is explicitly included/pinned in (flag rules ignored)."""
    out = {}
    for f in tg.dialog_filters(client):
        title = getattr(f, "title", None)
        if title is None:  # DialogFilterDefault ("All chats")
            continue
        title = getattr(title, "text", title)  # layer >=193: TextWithEntities
        seen = set()
        for p in list(getattr(f, "pinned_peers", None) or []) + list(getattr(f, "include_peers", None) or []):
            if any(hasattr(p, a) for a in ("channel_id", "chat_id", "user_id")):
                pid = peer_key(p)
                if pid not in seen:
                    seen.add(pid)
                    out.setdefault(pid, []).append(title)
    return out


def _notify_scope(e):
    k = kind(e)
    return "users" if k in ("user", "bot") else "broadcasts" if k == "channel" else "chats"


def _muted(d, defaults):
    """Own mute_until, else the account default for the peer type."""
    until = getattr(getattr(getattr(d, "dialog", None), "notify_settings", None), "mute_until", None)
    if until is None:
        until = defaults.get(_notify_scope(d.entity))
    if until is None:
        return False
    if isinstance(until, datetime):
        return until > datetime.now(timezone.utc)
    return until > time.time()


def dialogs(client, flt=None, kinds=None, limit=50):
    """Dialog rows, newest first. Filtering scans every dialog; unfiltered stops at limit."""
    scan = None if (flt or kinds) else limit
    in_folders, defaults = folders(client), tg.notify_defaults(client)
    out = []
    for d in client.iter_dialogs(limit=scan):
        e = d.entity
        if kinds and kind(e) not in kinds:
            continue
        if flt and flt.casefold() not in _text(e):
            continue
        pid = peer_id(e)
        out.append(row(e, unread=d.unread_count, last=iso(d.date), muted=_muted(d, defaults),
                       archived=bool(getattr(d, "archived", False)), pinned=bool(getattr(d, "pinned", False)),
                       folders=in_folders.get(pid, []), members=getattr(e, "participants_count", None),
                       unread_mentions=getattr(d, "unread_mentions_count", 0) or 0))
        if len(out) >= limit:
            break
    return out


# ---- people search ---------------------------------------------------------------

def find(client, query, limit=20):
    """Contacts (substring on name/username/phone) + exact @username + contacts.search (mine, then global)."""
    q = query.strip().lstrip("@")
    qf = q.casefold()
    found = {}

    def add(e, source, phone=None):
        pid = peer_id(e)
        if pid not in found:
            found[pid] = row(e, phone=phone, source=source)

    for u in tg.contacts(client):
        if qf in " ".join(filter(None, (name(u), username(u), getattr(u, "phone", None)))).casefold():
            add(u, "contact", getattr(u, "phone", None))
    if USERNAME_RE.fullmatch(q):
        e = tg.resolve_username(client, q)
        if e is not None:
            add(e, "username")
    if len(q) >= 3:  # contacts.search rejects shorter queries (QUERY_TOO_SHORT)
        res = tg.search_peers(client, q, limit)
        ents = {peer_id(e): e for e in list(res.users) + list(res.chats)}
        for source, peers in (("mine", res.my_results), ("global", res.results)):
            for p in peers:
                e = ents.get(peer_key(p))
                if e is not None:
                    add(e, source)
    return list(found.values())[:limit]


# ---- resolving a chat reference -------------------------------------------------

def resolve(client, ref):
    """me | numeric id | @username | t.me link | dialog/contact name. Ambiguous or unknown -> exit 2."""
    ref = ref.strip()
    if ref.casefold() in SELF:
        return client.get_me()
    if re.fullmatch(r"-?\d+", ref):
        try:
            return client.get_entity(int(ref))
        except ValueError:
            raise UsageError(f"id {ref} is unknown to this account - take ids from tg-cli chats / user-find") from None
    m = LINK_RE.match(ref)
    if ref.startswith("@") or m:
        uname = m.group(1) if m else ref[1:]
        e = tg.resolve_username(client, uname)
        if e is None:
            raise UsageError(f"@{uname} does not exist - try: tg-cli user-find {uname}")
        return e
    return _by_name(client, ref)


def _by_name(client, ref):
    """Dialog titles and contact names: exact (case-insensitive) match wins, else substring; must be unique."""
    rf = ref.casefold()
    pool = {}
    for d in client.iter_dialogs():
        pool.setdefault(peer_id(d.entity), d.entity)
    for u in tg.contacts(client):
        pool.setdefault(peer_id(u), u)
    exact = [e for e in pool.values() if (name(e) or "").casefold() == rf]
    hits = exact or [e for e in pool.values() if rf in _text(e)]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise UsageError(f"no chat or contact named {ref!r} - for a username use @{ref}; "
                         f"to find people: tg-cli user-find {ref!r}")
    raise UsageError(f"{len(hits)} chats match {ref!r} - nothing done; repeat with an id or @username:",
                     payload=[row(e) for e in hits[:MAX_CANDIDATES]])
