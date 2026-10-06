"""Message vocabulary over the store: rows, history, search; send (network)."""
import os

from ..core.errors import UsageError
from . import normalize
from .peers import Names, iso_ts

MSG_FIELDS = ["date", "chat_jid", "chat", "msg_id", "sender", "text"]
RECEIPT_FIELDS = ["id", "chat_jid", "chat", "date"]


def _epoch(dt):
    return int(dt.timestamp()) if dt else None


def row(m, names, text_limit=None):
    text = m["text"] or ""
    cut = bool(text_limit) and len(text) > text_limit
    sender = "me" if m["from_me"] else (names.name(m["sender_jid"]) if m["sender_jid"] else None)
    if sender and sender.startswith("+") and m["sender_name"]:
        sender = f"{m['sender_name']} ({sender})"  # unknown number: show the name they chose
    return {"date": iso_ts(m["ts"]), "chat_jid": m["chat_jid"], "chat": names.name(m["chat_jid"]), "msg_id": m["id"],
            "sender": sender, "sender_jid": m["sender_jid"], "kind": m["kind"], "file": m.get("file"),
            "text": text[:text_limit] + "…" if cut else text, "truncated": cut,
            "server_id": m["server_id"], "views": m["views"]}


def history(store, chat_jids, limit=20, since=None, sender_jids=None, text_limit=None):
    names = Names(store)
    return [row(m, names, text_limit) for m in store.messages(chat_jids, None, sender_jids, _epoch(since), None, limit)]


def search(store, query, chat_jids=None, sender_jids=None, since=None, until=None, limit=50, text_limit=None):
    if not query and not chat_jids:
        raise UsageError("a query is required unless --chat is given")
    names = Names(store)
    return [row(m, names, text_limit)
            for m in store.messages(chat_jids, query or None, sender_jids, _epoch(since), _epoch(until), limit)]


def check_target(session, store, jid):
    """A phone jid nobody in the store has talked to: ask WhatsApp it exists (a send to a non-user
    jid fails silently on the phone side). -> the jid WhatsApp knows it by."""
    if (not jid.endswith("@s.whatsapp.net") or jid == store.get_meta("me_jid") or store.chat(jid)
            or store.contact(jid)):
        return jid
    res = session.on_whatsapp("+" + jid.split("@")[0])
    if not res or not res[0]["is_in"]:
        raise UsageError(f"+{jid.split('@')[0]} is not on WhatsApp - nothing sent")
    return res[0]["jid"] or jid


def _record(store, jid, sent, me, kind, text):
    store.upsert_chat(jid, kind=normalize.chat_kind(jid))
    store.upsert_message({"chat_jid": jid, "id": sent["id"], "ts": sent["ts"], "sender_jid": me, "sender_name": None,
                          "from_me": 1, "kind": kind, "text": text, "server_id": sent["server_id"], "views": None})
    store.commit()


def _receipt(names, jid, sent):
    return {"id": sent["id"], "chat_jid": jid, "chat": names.name(jid), "date": iso_ts(sent["ts"])}


def send(session, store, jid, text):
    if not text.strip():
        raise UsageError("empty message - nothing sent")
    sent = session.send_text(jid, text)
    _record(store, jid, sent, store.get_meta("me_jid"), "text", text)
    return _receipt(Names(store), jid, sent)


def send_files(session, store, jid, paths, caption=""):
    """Each file is its own document message (WhatsApp has no albums for documents); caption on the first."""
    out = []
    for i, path in enumerate(paths):
        cap = caption if i == 0 else ""
        sent = session.send_document(jid, path, cap or None)
        _record(store, jid, sent, store.get_meta("me_jid"), "document",
                " ".join(p for p in ("[document]", os.path.basename(path), cap) if p))
        out.append(_receipt(Names(store), jid, sent))
    return out
