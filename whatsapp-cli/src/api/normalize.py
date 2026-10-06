"""Protos -> store rows. Duck-typed (HasField/getattr), so tests feed plain fakes and neonize stays out.

One message proto -> content(): ("msg", kind, text) | ("edit", target_id, text) | ("revoke", target_id) | None.
media_of(): the download keys of image/video/audio/sticker/document content, kept in the store for `download`.
"""
from ..core.wa import jid_str, norm_ts

WRAPPERS = ("ephemeralMessage", "viewOnceMessage", "viewOnceMessageV2", "viewOnceMessageV2Extension",
            "documentWithCaptionMessage", "editedMessage")
# Set on real messages but carry no content of their own.
NOISE = {"messageContextInfo", "senderKeyDistributionMessage"}
# Not a message a person reads: reactions, poll votes, pins, keep-in-chat, receipts of other protocol ops.
SKIP = {"reactionMessage", "encReactionMessage", "pollUpdateMessage", "keepInChatMessage", "pinInChatMessage",
        "encEventResponseMessage", "secretEncryptedMessage", "protocolMessage", "botInvokeMessage"}
REVOKE, MESSAGE_EDIT = 0, 14  # waE2E.ProtocolMessage.Type
# Downloadable content: proto fields and the kinds content() gives them.
MEDIA = ("imageMessage", "videoMessage", "ptvMessage", "stickerMessage", "audioMessage", "documentMessage")
MEDIA_KINDS = ("image", "video", "sticker", "audio", "voice", "document")


def has(m, field):
    try:
        return m.HasField(field)
    except (AttributeError, ValueError):
        return bool(getattr(m, field, None))


def unwrap(m):
    for _ in range(4):  # wrappers nest (ephemeral(viewOnce(...)))
        for w in WRAPPERS:
            if has(m, w):
                m = getattr(m, w).message
                break
        else:
            return m
    return m


def _set_fields(m):
    try:
        return [f.name for f, _ in m.ListFields()]
    except AttributeError:
        return [k for k, v in vars(m).items() if v]


def _join(*parts):
    return " ".join(p for p in parts if p)


def content(m):
    if m is None:
        return None
    m = unwrap(m)
    if has(m, "protocolMessage"):
        p = m.protocolMessage
        target = getattr(p.key, "ID", None)
        if p.type == REVOKE and target:
            return ("revoke", target)
        if p.type == MESSAGE_EDIT and target:
            got = content(p.editedMessage)
            return ("edit", target, got[2]) if got and got[0] == "msg" else None
        return None
    if getattr(m, "conversation", ""):
        return ("msg", "text", m.conversation)
    if has(m, "extendedTextMessage"):
        return ("msg", "text", m.extendedTextMessage.text)
    media = (("imageMessage", "image"), ("videoMessage", "video"), ("ptvMessage", "video"), ("stickerMessage", "sticker"))
    for field, kind in media:
        if has(m, field):
            return ("msg", kind, _join(f"[{kind}]", getattr(getattr(m, field), "caption", "")))
    if has(m, "audioMessage"):
        kind = "voice" if getattr(m.audioMessage, "PTT", False) else "audio"
        return ("msg", kind, f"[{kind}]")
    if has(m, "documentMessage"):
        d = m.documentMessage
        return ("msg", "document", _join("[document]", d.fileName, d.caption))
    if has(m, "contactMessage"):
        return ("msg", "contact", _join("[contact]", m.contactMessage.displayName))
    if has(m, "contactsArrayMessage"):
        return ("msg", "contact", _join("[contacts]", m.contactsArrayMessage.displayName))
    for field in ("locationMessage", "liveLocationMessage"):
        if has(m, field):
            loc = getattr(m, field)
            return ("msg", "location", _join("[location]", getattr(loc, "name", ""), getattr(loc, "address", "")))
    for field in ("pollCreationMessage", "pollCreationMessageV2", "pollCreationMessageV3"):
        if has(m, field):
            poll = getattr(m, field)
            opts = " / ".join(o.optionName for o in getattr(poll, "options", []))
            return ("msg", "poll", _join("[poll]", poll.name, f"({opts})" if opts else ""))
    rest = [f for f in _set_fields(m) if f not in NOISE]
    if not rest or any(f in SKIP for f in rest):
        return None
    return ("msg", "other", f"[{rest[0].replace('Message', '')}]")


def _blob(m, field):
    """Only the media part of m, serialized: what DownloadAny needs (url, direct path, key, hashes, mime, name).
    Thumbnail and quote context dropped (size). Real protos only; fakes -> None."""
    try:
        out = type(m)()
        part = getattr(out, field)
        part.CopyFrom(getattr(m, field))
        for f in ("JPEGThumbnail", "contextInfo"):
            try:
                part.ClearField(f)
            except ValueError:
                pass
        return out.SerializeToString()
    except (AttributeError, TypeError):
        return None


def media_of(m):
    """Message proto -> {"file": original file name|None, "mime", "media": bytes|None} for downloadable content."""
    if m is None:
        return None
    m = unwrap(m)
    for field in MEDIA:
        if has(m, field):
            part = getattr(m, field)
            return {"file": getattr(part, "fileName", "") or None, "mime": getattr(part, "mimetype", "") or None,
                    "media": _blob(m, field)}
    return None


def _with_media(row, message):
    got = media_of(message) or {}
    row["file"], row["mime"], row["media"] = got.get("file"), got.get("mime"), got.get("media")
    return row


def chat_kind(jid):
    server = (jid or "").rpartition("@")[2]
    return {"g.us": "group", "newsletter": "channel", "broadcast": "broadcast"}.get(server, "user")


SYSTEM_JID = "0@s.whatsapp.net"  # WhatsApp's own service chat (security codes, notices): no phone


def phone_of(jid):
    user, _, server = (jid or "").rpartition("@")
    return f"+{user}" if server == "s.whatsapp.net" and user.isdigit() and user != "0" else None


# ---- group events -------------------------------------------------------------------

def group_update(kind, ev):
    """GroupInfoEvent (name/topic/... change) or JoinedGroup (added to a group) -> chat row | None."""
    if kind == "joined_group":
        g = ev.GroupInfo
        jid = jid_str(g.JID)
        return {"jid": jid, "kind": "group", "name": g.GroupName.Name or None,
                "last_ts": norm_ts(g.GroupCreated)} if jid else None
    jid = jid_str(ev.JID)
    if not jid:
        return None
    name = ev.Name.Name if has(ev, "Name") else None
    return {"jid": jid, "kind": "group", "name": name or None, "last_ts": None}


# ---- live MessageEv -----------------------------------------------------------------

def live(ev):
    """neonize Message event -> (row|None, op) where op is content()'s tuple; row has store MSG_COLS +
    alt jids for the chat/sender (WhatsApp addresses one person by phone jid and by lid jid)."""
    info = ev.Info
    src = info.MessageSource
    got = content(ev.Message)
    chat = jid_str(src.Chat)
    if got is None or not chat or chat == "status@broadcast":
        return None, None
    from_me = bool(src.IsFromMe)
    row = {"chat_jid": chat, "id": info.ID, "ts": norm_ts(info.Timestamp), "sender_jid": jid_str(src.Sender),
           "sender_name": None if from_me else (info.Pushname or None), "from_me": int(from_me),
           "server_id": getattr(info, "ServerID", 0) or None, "views": None,
           "chat_alt": None, "sender_alt": jid_str(getattr(src, "SenderAlt", None))}
    if not src.IsGroup and chat_kind(chat) == "user":
        row["chat_alt"] = jid_str(getattr(src, "RecipientAlt" if from_me else "SenderAlt", None))
    if chat_kind(chat) == "channel" and row["server_id"]:
        row["id"] = f"s{row['server_id']}"  # same key as channel-fetch posts
    if got[0] == "msg":
        row["kind"], row["text"] = got[1], got[2]
        _with_media(row, ev.Message)
    return row, got


# ---- HistorySync ----------------------------------------------------------------------

def history(data, me_jid=None):
    """waHistorySync.HistorySync -> (chats, messages, pushnames). Rows only; ops (edit/revoke) in
    history are already applied by the phone, so they are dropped."""
    chats, msgs = [], []
    for conv in data.conversations:
        jid = conv.ID
        if not jid or jid == "status@broadcast":
            continue
        alt = next((a for a in (getattr(conv, "pnJID", ""), getattr(conv, "lidJID", "")) if a and a != jid), None)
        chats.append({"jid": jid, "kind": chat_kind(jid), "name": conv.name or conv.displayName or None,
                      "alt_jid": alt, "last_ts": norm_ts(conv.conversationTimestamp),
                      "unread": conv.unreadCount})
        group = chat_kind(jid) == "group"
        for hm in conv.messages:
            w = hm.message
            got = content(w.message) if has(w, "message") else None
            if not got or got[0] != "msg":
                continue
            from_me = bool(w.key.fromMe)
            if from_me:
                sender = me_jid
            elif group:
                sender = w.key.participant or w.participant or None
            else:
                sender = jid
            msgs.append(_with_media({"chat_jid": jid, "id": w.key.ID, "ts": norm_ts(w.messageTimestamp),
                                     "sender_jid": sender, "sender_name": None if from_me else (w.pushName or None),
                                     "from_me": int(from_me), "kind": got[1], "text": got[2], "server_id": None,
                                     "views": None}, w.message))
    pushnames = [(p.ID, p.pushname) for p in data.pushnames if p.ID and p.pushname]
    return chats, msgs, pushnames


# ---- channel posts ----------------------------------------------------------------------

def post(channel_jid, server_id, views, message):
    got = content(message)
    if not got or got[0] != "msg":
        return None
    return _with_media({"chat_jid": channel_jid, "id": f"s{server_id}", "ts": None, "sender_jid": channel_jid,
                        "sender_name": None, "from_me": 0, "kind": got[1], "text": got[2], "server_id": server_id,
                        "views": views or None}, message)
