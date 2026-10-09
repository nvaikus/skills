"""The only store writer: events from a connected session -> store rows.

drain() runs on every command's connect; absorb() takes what was still queued at disconnect (the server
acks a delivered message once and never resends it, so nothing in the queue may be dropped). A future
`sync --follow` daemon = connect once + apply() in a loop.
"""
import time

from . import normalize, peers

REFRESH_EVERY = 3600  # s between address-book/group-list refreshes (contacts are local, groups one request)


def me_jid(store, session):
    jid = store.get_meta("me_jid")
    if not jid:
        me = session.me()
        jid = me["jid"]
        store.set_meta("me_jid", jid)
        if me.get("lid"):
            store.set_meta("me_lid", me["lid"])
    return jid


def apply(kind, ev, store, me=None, stats=None):
    stats = stats if stats is not None else {}
    if kind == "message":
        row, op = normalize.live(ev)
        if row is None:
            return stats
        if op[0] == "edit":
            store.edit_message(row["chat_jid"], op[1], op[2])
        elif op[0] == "revoke":
            store.delete_message(row["chat_jid"], op[1])
        else:
            store.upsert_chat(row["chat_jid"], kind=normalize.chat_kind(row["chat_jid"]), alt_jid=row["chat_alt"])
            if row["sender_jid"] and not row["from_me"]:
                store.upsert_contact(row["sender_jid"], phone=normalize.phone_of(row["sender_jid"])
                                     or normalize.phone_of(row["sender_alt"]), push_name=row["sender_name"])
            if store.upsert_message(row):
                stats["messages"] = stats.get("messages", 0) + 1
    elif kind in ("group_info", "joined_group"):
        c = normalize.group_update(kind, ev)
        if c:
            store.upsert_chat(c["jid"], kind="group", name=c["name"], last_ts=c["last_ts"], members=c.get("members"))
            stats["groups"] = stats.get("groups", 0) + 1
    elif kind == "history":
        chats, msgs, pushnames = normalize.history(ev.Data, me)
        for c in chats:
            store.upsert_chat(**c)
        for jid, name in pushnames:
            store.upsert_contact(jid, phone=normalize.phone_of(jid), push_name=name)
        stats["history_chats"] = stats.get("history_chats", 0) + len(chats)
        for m in msgs:
            if store.upsert_message(m):
                stats["messages"] = stats.get("messages", 0) + 1
    return stats


def nameless_groups(store):
    return sorted(c["jid"] for c in store.chats() if c["kind"] == "group" and not c["name"])


def refresh(session, store, force=False):
    """Address book (whatsmeow's local copy of the phone's contacts) + joined groups' names + followed channels.
    Hourly, and at once when a group has no name yet (created/joined after the history sync); a group
    still nameless after that (left it) does not force another refresh until the nameless set changes."""
    last = int(store.get_meta("refreshed", "0") or 0)
    nameless = ",".join(nameless_groups(store))
    if nameless and nameless != (store.get_meta("nameless_tried") or ""):
        force = True
    if not force and time.time() - last < REFRESH_EVERY:
        return
    for c in session.contacts():
        store.upsert_contact(c["jid"], phone=normalize.phone_of(c["jid"]), full_name=c["full_name"],
                             first_name=c["first_name"], push_name=c["push_name"], business_name=c["business_name"])
    for g in session.groups():
        store.upsert_chat(g["jid"], kind="group", name=g["name"], last_ts=g["created"], members=g.get("participants"))
    mark_followed(session, store)
    store.set_meta("nameless_tried", ",".join(nameless_groups(store)))
    store.set_meta("refreshed", int(time.time()))


def mark_followed(session, store):
    """Followed channels into chats; every other stored channel marked not-following (hidden by `chats`).
    A failed request marks nothing - the next refresh tries again."""
    try:
        subs = session.subscribed_newsletters()
    except Exception:  # noqa: BLE001 - optional refresh, never fails a read
        return
    for n in subs:
        store.upsert_chat(n["jid"], kind="channel", name=n["name"], info=peers.FOLLOWING)
    followed = {n["jid"] for n in subs}
    for c in store.chats():
        if c["kind"] == "channel" and c["jid"] not in followed:
            store.upsert_chat(c["jid"], info=peers.NOT_FOLLOWING)


def drain(session, store, maximum=20, quiet=1.5, force_refresh=False):
    """Pull everything queued for this device into the store. -> stats dict."""
    me = me_jid(store, session)
    stats = {}
    for kind, ev in session.events(quiet=quiet, maximum=maximum):
        apply(kind, ev, store, me, stats)
        store.commit()
    refresh(session, store, force_refresh)
    store.set_meta("synced", int(time.time()))
    store.commit()
    return stats


def absorb(events, store, session=None):
    me = store.get_meta("me_jid")
    for kind, ev in events:
        apply(kind, ev, store, me)
    store.commit()
