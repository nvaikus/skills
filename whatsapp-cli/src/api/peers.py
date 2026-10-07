"""Chat/person vocabulary over the store: display names, rows, resolving a reference to jids.

WhatsApp addresses one person by a phone jid (<digits>@s.whatsapp.net) and a privacy jid (<n>@lid);
a chat row may carry the other one in alt_jid, so a resolved target is a list of jids.
"""
import re
from datetime import datetime, timezone

from ..core.errors import UsageError
from .normalize import SYSTEM_JID, chat_kind, phone_of

PEER_FIELDS = ["jid", "type", "name", "phone"]
SELF = ("me", "self")
PHONE_RE = re.compile(r"\+?[\d][\d\s().-]{5,}\d")
MAX_CANDIDATES = 10


def iso_ts(ts):
    return datetime.fromtimestamp(ts, timezone.utc).astimezone().isoformat(timespec="seconds") if ts else None


def phone_jid(ref):
    digits = re.sub(r"\D", "", ref)
    return f"{digits}@s.whatsapp.net"


class Names:
    """jid -> display name: chat name, else address-book name, else push name, else +phone."""

    def __init__(self, store):
        self.store = store
        self.chats = {c["jid"]: c for c in store.chats()}
        self.contacts = {c["jid"]: c for c in store.contacts()}
        self.linked = {}  # jid -> other jids of the same person (a phone chat and a lid chat may both exist)
        for c in list(self.chats.values()):
            if c["alt_jid"]:
                self.chats.setdefault(c["alt_jid"], c)
                self.linked.setdefault(c["jid"], set()).add(c["alt_jid"])
                self.linked.setdefault(c["alt_jid"], set()).add(c["jid"])
        self.me = store.get_meta("me_jid")
        self.me_lid = store.get_meta("me_lid")

    def contact_name(self, jid):
        c = self.contacts.get(jid)
        if c:
            return c["full_name"] or c["push_name"] or c["business_name"] or c["first_name"]
        return None

    def name(self, jid):
        if not jid:
            return None
        if jid in (self.me, self.me_lid):
            return "me"
        if jid == SYSTEM_JID:
            return "WhatsApp"
        c = self.chats.get(jid)
        alt = c["alt_jid"] if c else None
        return ((c and c["name"]) or self.contact_name(jid) or (alt and self.contact_name(alt))
                or phone_of(jid) or phone_of(alt) or jid)

    def phone(self, jid):
        c = self.chats.get(jid)
        return phone_of(jid) or (c and phone_of(c["alt_jid"])) or (self.contacts.get(jid) or {}).get("phone")

    def row(self, jid, **extra):
        r = {"jid": jid, "type": chat_kind(jid), "name": self.name(jid), "phone": self.phone(jid)}
        r.update(extra)
        return r

    def pool(self):
        """Every chat and contact once (a chat's alt jid folds into the chat)."""
        seen, out = set(), []
        for jid, c in self.chats.items():
            if c["jid"] in seen:
                continue
            seen.update(self.jids(c["jid"]))
            out.append(c["jid"])
        for jid in self.contacts:
            if jid not in seen:
                seen.add(jid)
                out.append(jid)
        return out

    def text(self, jid):
        c = self.chats.get(jid) or {}
        parts = (self.name(jid), self.contact_name(jid), (self.contacts.get(jid) or {}).get("push_name"),
                 self.phone(jid), jid)
        return " ".join(p for p in parts if p).casefold() + " " + (c.get("name") or "").casefold()

    def jids(self, jid):
        c = self.chats.get(jid)
        return [j for j in dict.fromkeys((jid, c and c["jid"], c and c["alt_jid"], *sorted(self.linked.get(jid, ()))))
                if j]


# ---- listings -----------------------------------------------------------------

# chats.info of a channel: whether this account follows it (set by channel-info/fetch and the hourly refresh).
FOLLOWING, NOT_FOLLOWING = "following", "not-following"


def chat_rows(store, flt=None, kinds=None, limit=50, unfollowed=False):
    """unfollowed=False hides channels the account does not follow (their posts came from channel-fetch)."""
    names = Names(store)
    out = []
    for c in store.chats():
        if kinds and c["kind"] not in kinds:
            continue
        extra = {}
        if c["kind"] == "channel":
            if c["info"] == NOT_FOLLOWING and not unfollowed:
                continue
            extra["following"] = {FOLLOWING: True, NOT_FOLLOWING: False}.get(c["info"])
        r = names.row(c["jid"], unread=c["unread"], last=iso_ts(c["last_ts"]), **extra)
        if flt and flt.casefold() not in names.text(c["jid"]):
            continue
        out.append(r)
        if len(out) >= limit:
            break
    return out


def contact_rows(store, flt=None, limit=500):
    names = Names(store)
    out = []
    for c in store.contacts():
        if not (c["full_name"] or c["first_name"]):  # pushname-only = not in the address book
            continue
        if flt and flt.casefold() not in names.text(c["jid"]):
            continue
        out.append({"jid": c["jid"], "name": c["full_name"] or c["first_name"], "phone": c["phone"],
                    "push_name": c["push_name"], "business_name": c["business_name"]})
        if len(out) >= limit:
            break
    return out


def find(store, query, limit=20):
    """Substring over chat names, address-book names, push names, phones and jids."""
    names = Names(store)
    q = query.strip().casefold()
    digits = re.sub(r"\D", "", q)
    out = []
    for jid in names.pool():
        hay = names.text(jid)
        if q in hay or (len(digits) >= 4 and PHONE_RE.fullmatch(query.strip()) and digits in re.sub(r"\D", "", hay)):
            src = "contact" if (names.contacts.get(jid) or {}).get("full_name") else ("chat" if jid in names.chats else "seen")
            out.append(names.row(jid, source=src))
            if len(out) >= limit:
                break
    return out


# ---- resolving a reference --------------------------------------------------------

def resolve(store, ref, kinds=None):
    """me | +phone / digits | full jid | exact or unique chat/contact name -> (jid, [jids], name).
    Unknown or ambiguous -> exit 2 (with candidates)."""
    ref = ref.strip()
    names = Names(store)
    if ref.casefold() in SELF:
        if not names.me:
            raise UsageError("own jid unknown yet - run any command without --offline once")
        return names.me, [j for j in (names.me, names.me_lid) if j], "me"
    if "@" in ref:
        return ref, names.jids(ref), names.name(ref)
    if PHONE_RE.fullmatch(ref):
        jid = phone_jid(ref)
        return jid, names.jids(jid), names.name(jid)
    rf = ref.casefold()
    pool = [j for j in names.pool() if not kinds or chat_kind(j) in kinds]
    exact = [j for j in pool if (names.name(j) or "").casefold() == rf or (names.contact_name(j) or "").casefold() == rf]
    hits = exact or [j for j in pool if rf in names.text(j)]
    if len(hits) == 1:
        return hits[0], names.jids(hits[0]), names.name(hits[0])
    if not hits:
        raise UsageError(f"no chat or contact matches {ref!r} in the local store - try: wa-cli user-find {ref!r}; "
                         "a phone number (+351...) or jid works too")
    raise UsageError(f"{len(hits)} chats match {ref!r} - nothing done; repeat with a jid or phone:",
                     payload=[names.row(j) for j in hits[:MAX_CANDIDATES]])
