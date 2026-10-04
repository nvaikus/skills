"""Group invite links: what they point to, joining."""
import re

from ..core.errors import UsageError
from .peers import iso_ts

GROUP_FIELDS = ["jid", "name", "participants", "member", "owner", "created"]
LINK_RE = re.compile(r"(?:https?://)?chat\.whatsapp\.com/(?:invite/)?([A-Za-z0-9]{10,40})/?(?:\?.*)?$")
CODE_RE = re.compile(r"[A-Za-z0-9]{10,40}")


def invite_code(ref):
    ref = ref.strip()
    m = LINK_RE.match(ref)
    if m:
        return m.group(1)
    if CODE_RE.fullmatch(ref):
        return ref
    raise UsageError(f"not a group invite link: {ref!r} - expected https://chat.whatsapp.com/<code>")


def row(g):
    r = dict(g)
    r["created"] = iso_ts(g.get("created"))
    owner = g.get("owner") or ""
    r["owner"] = f"+{owner.split('@')[0]}" if owner.endswith("@s.whatsapp.net") else owner or None
    return r


def info(session, store, ref):
    """The link preview lists only some participants (seen: 1 of 3) and no total. For a group this account
    is in, the full info gives the real count; otherwise participants stays empty (preview count in
    participants_preview)."""
    g = session.group_from_link(invite_code(ref))
    preview = g.get("participants")
    known = store.chat(g["jid"]) if g.get("jid") else None
    full = None
    if known and known["kind"] == "group":
        try:
            full = session.group(g["jid"])
        except Exception:  # noqa: BLE001  left the group since: the preview is all there is
            full = None
    out = row(full or g)
    out["member"] = full is not None
    out["participants"] = full["participants"] if full else None
    out["participants_preview"] = preview
    return out


def join(session, store, ref):
    code = invite_code(ref)
    g = session.group_from_link(code)  # validates the link and names the group before anything changes
    jid = session.join_link(code) or g["jid"]
    store.upsert_chat(jid, kind="group", name=g["name"])
    store.commit()
    out = row(g)
    out.update(jid=jid, member=True, participants=None, participants_preview=g.get("participants"))
    return out
