"""Message vocabulary: rows, history, search (dialogs / one chat / public posts), send."""
from datetime import datetime, timezone

from ..core import tg
from ..core.errors import Refused, UsageError
from ..core.timeparse import iso
from . import peers

MSG_FIELDS = ["date", "chat_id", "chat", "msg_id", "sender", "text"]


def media_label(m):
    media = getattr(m, "media", None)
    if media is None or type(media).__name__ == "MessageMediaWebPage":  # link preview: the URL is already in the text
        return None
    return "[" + type(media).__name__.replace("MessageMedia", "").lower() + "]"


def row(m, chat, sender, text_limit=None):
    text = getattr(m, "message", None) or ""
    label = media_label(m)
    if label:
        text = f"{label} {text}".strip()
    cut = bool(text_limit) and len(text) > text_limit
    return {"date": iso(m.date), "chat_id": peers.peer_id(chat) if chat is not None else None,
            "chat": peers.name(chat) if chat is not None else None, "msg_id": m.id,
            "sender": peers.name(sender) if sender is not None else None,
            "sender_id": peers.peer_id(sender) if sender is not None else None,
            "text": text[:text_limit] + "…" if cut else text, "truncated": cut,
            "link": peers.link(chat, m.id)}


def _collect(it, since, limit, text_limit):
    """Newest-first iterator -> rows; stops at `since` or `limit`."""
    out = []
    for m in it:
        if since and m.date < since:
            break
        out.append(row(m, m.chat, m.sender, text_limit))
        if len(out) >= limit:
            break
    return out


def history(client, chat, limit=20, since=None, sender=None, text_limit=None):
    return _collect(client.iter_messages(chat, from_user=sender), since, limit, text_limit)


def search(client, query, chat=None, sender=None, since=None, until=None, limit=50, text_limit=None):
    """chat=None -> messages.searchGlobal over every dialog of the account; else messages.search in one chat."""
    if chat is None and not query:
        raise UsageError("a query is required unless --chat is given")
    if chat is None and sender is not None:
        raise UsageError("--from needs --chat (Telegram's global search has no sender filter)")
    it = client.iter_messages(chat, search=query or None, from_user=sender, offset_date=until)
    return _collect(it, since, limit, text_limit)


def search_public(client, query, limit=20, text_limit=None):
    """channels.searchPosts over all public channels. '#tag' is a free hashtag search; words use the daily
    free quota. Returns (rows, flood-or-None). Never spends Stars: out of free slots -> exit 3."""
    tag = query[1:] if query.startswith("#") and " " not in query else None
    flood = None
    if tag is None:
        flood = tg.posts_flood(client, query)
        if not flood.query_is_free and flood.remains <= 0:
            nxt = iso(datetime.fromtimestamp(flood.wait_till, timezone.utc)) if flood.wait_till else "unknown"
            raise Refused(f"public post search: free daily quota used up ({flood.total_daily}/day), next free "
                          f"search at {nxt}; a paid search costs {flood.stars_amount} Stars and tg-cli never "
                          f"spends Stars - nothing was sent. Hashtag searches ('#tag') stay free.")
    res = tg.search_posts(client, None if tag else query, tag, limit)
    ents = {peers.peer_id(e): e for e in list(res.chats) + list(res.users)}
    rows = []
    for m in res.messages:
        chat = ents.get(peers.peer_key(m.peer_id))
        sender = ents.get(peers.peer_key(m.from_id)) if getattr(m, "from_id", None) else chat
        rows.append(row(m, chat, sender, text_limit))
    return rows, flood


def _receipt(chat, m):
    return {"id": m.id, "chat_id": peers.peer_id(chat), "chat": peers.name(chat), "date": iso(m.date),
            "link": peers.link(chat, m.id)}


def send(client, chat, text, markdown=False, reply_to=None):
    if not text.strip():
        raise UsageError("empty message - nothing sent")
    m = client.send_message(chat, text, parse_mode="md" if markdown else None, reply_to=reply_to)
    return _receipt(chat, m)


def send_files(client, chat, paths, caption="", markdown=False, reply_to=None):
    """Files as documents (no recompression); several = one album, caption on the first. -> receipts."""
    sent = client.send_file(chat, paths[0] if len(paths) == 1 else list(paths), caption=caption or None,
                            force_document=True, parse_mode="md" if markdown else None, reply_to=reply_to)
    return [_receipt(chat, m) for m in (sent if isinstance(sent, list) else [sent])]
