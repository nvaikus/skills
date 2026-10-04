"""Channels (newsletters): info by link/code/jid/name, recent posts. Never follows a channel.

Reading posts needs no follow (verified live 2026-10-04 on a channel the account does not follow).
Directory search (WhatsApp's "Find channels") is not exposed by whatsmeow/neonize - no command for it.
"""
import re

from ..core.errors import UsageError
from . import normalize, peers

CHANNEL_FIELDS = ["jid", "name", "subscribers", "verified", "following", "invite"]
POST_FIELDS = ["msg_id", "reactions", "text"]
LINK_RE = re.compile(r"(?:https?://)?(?:www\.)?whatsapp\.com/channel/([A-Za-z0-9]{10,40})/?(?:\?.*)?$")
CODE_RE = re.compile(r"[A-Za-z0-9]{15,40}")


def _ref(store, ref):
    """-> ("jid", jid) | ("code", invite code)."""
    ref = ref.strip()
    if ref.endswith("@newsletter"):
        return "jid", ref
    m = LINK_RE.match(ref)
    if m:
        return "code", m.group(1)
    try:
        return "jid", peers.resolve(store, ref, kinds=("channel",))[0]
    except UsageError as e:
        if CODE_RE.fullmatch(ref) and not e.payload:
            return "code", ref
        raise


def info(session, store, ref):
    """following = the jid is in the account's subscribed list (whatsmeow's viewer role is no follow flag:
    it reads "subscriber" for a channel the account does not follow)."""
    how, val = _ref(store, ref)
    ch = session.newsletter(val) if how == "jid" else session.newsletter_by_invite(val)
    ch["following"] = ch["jid"] in {n["jid"] for n in session.subscribed_newsletters()}
    store.upsert_chat(ch["jid"], kind="channel", name=ch["name"],
                      info=peers.FOLLOWING if ch["following"] else peers.NOT_FOLLOWING)
    store.commit()
    return ch


def fetch(session, store, ref, count=20, text_limit=None):
    """Latest `count` posts into the store; rows newest first. Posts carry no timestamp (neonize's
    newsletter message has none) - order is the server id. Views come back 0 unless the viewer is an
    admin, so they are dropped (None) then; reactions are what a subscriber sees."""
    ch = info(session, store, ref)
    rows = []
    for server_id, views, reacts, msg in session.newsletter_messages(ch["jid"], count):
        r = normalize.post(ch["jid"], server_id, views, msg)
        if r is None:
            continue
        store.upsert_message(r)
        text = r["text"] or ""
        cut = bool(text_limit) and len(text) > text_limit
        top = sorted(reacts.items(), key=lambda kv: -kv[1])
        rows.append({"msg_id": r["id"], "server_id": server_id, "reactions": sum(reacts.values()),
                     "top_reactions": " ".join(f"{k}{v}" for k, v in top[:5]) or None, "views": r["views"], "kind": r["kind"],
                     "text": text[:text_limit] + "…" if cut else text, "truncated": cut,
                     "chat_jid": ch["jid"], "chat": ch["name"]})
    store.commit()
    rows.sort(key=lambda r: r["server_id"], reverse=True)
    return ch, rows
