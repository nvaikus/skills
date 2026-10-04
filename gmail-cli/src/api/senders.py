"""Bulk-sender report: the messages of a query grouped by sender address, per profile.
Cost: messages.list 5 units per 500 ids + messages.get 5 per message; a thread with >= 2 matched
messages is one threads.get (10 units) instead. google's Pacer keeps it under the per-user quota
(~400 calls/min on a 6000-unit project)."""
from collections import Counter
from email.utils import parseaddr

from . import google, mail, unsubscribe

HEADERS = ["From", "Date", "Subject", "List-Unsubscribe", "List-Unsubscribe-Post"]
CATEGORY = {"CATEGORY_PERSONAL": "primary", "CATEGORY_SOCIAL": "social", "CATEGORY_PROMOTIONS": "promotions",
            "CATEGORY_UPDATES": "updates", "CATEGORY_FORUMS": "forums"}


def jobs(refs):
    """[{id, threadId}] -> [("m", id) | ("t", thread id)]: one threads.get per thread with >= 2 hits."""
    by_thread = {}
    for r in refs:
        by_thread.setdefault(r.get("threadId") or r["id"], []).append(r["id"])
    return [("t", tid) if len(ids) > 1 else ("m", ids[0]) for tid, ids in by_thread.items()]


def fetch(prof, refs):
    """Metadata (HEADERS only) of the referenced messages -> (messages, first error or None)."""
    want = {r["id"] for r in refs}
    params = {"format": "metadata", "metadataHeaders": HEADERS}

    def one(job):
        kind, i = job
        if kind == "m":
            return [google.get(prof, f"/messages/{i}", params)]
        t = google.get(prof, f"/threads/{i}", params) or {}
        return [m for m in t.get("messages", []) if m.get("id") in want]
    got, err = google.pmap_partial(one, jobs(refs))
    return [m for ms in got for m in ms if m], err


def aggregate(prof, msgs):
    """Messages -> one row per sender address (newest message sets name, subject, last)."""
    groups = {}
    for m in sorted(msgs, key=lambda x: int(x.get("internalDate") or 0), reverse=True):
        h = mail.headers(m.get("payload"))
        name, addr = parseaddr(h.get("from", ""))
        key = (addr or h.get("from", "") or "?").lower()
        labs = m.get("labelIds", [])
        g = groups.get(key)
        if g is None:
            g = groups[key] = {"profile": prof, "sender": key, "name": name, "count": 0, "unread": 0,
                               "last": mail.when(m.get("internalDate")), "ts": int(m.get("internalDate") or 0),
                               "_cats": Counter(), "subject": h.get("subject", ""), "unsubscribe": "-",
                               "latest_id": m["id"], "unsub_id": None}
        g["count"] += 1
        g["unread"] += "UNREAD" in labs
        g["_cats"].update(CATEGORY[x] for x in labs if x in CATEGORY)
        if g["unsubscribe"] == "-":
            how = unsubscribe.kind(h)
            if how != "-":
                g["unsubscribe"], g["unsub_id"] = how, m["id"]
        g["name"] = g["name"] or name
    rows = []
    for g in groups.values():
        cats = g.pop("_cats")
        g["category"] = cats.most_common(1)[0][0] if cats else "-"
        rows.append(g)
    return rows


def scan(prof, q, limit, note=None):
    """One profile -> (sender rows, problem or None)."""
    refs = mail.list_refs(prof, q, limit + 1)
    if len(refs) > limit:
        refs = refs[:limit]
        if note:
            note(f"profile {prof}: scanned the newest {limit} matches only; --limit N to widen")
    n = len(jobs(refs))
    if note and n * 5 > google.BURST * 2:
        note(f"profile {prof}: fetching {len(refs)} messages in {n} calls; Gmail's per-user quota may stretch "
             f"this to ~{-(-n // 400)} min")
    msgs, err = fetch(prof, refs)
    problem = mail.incomplete(prof, len(msgs), len(refs), err) if err else None
    return aggregate(prof, msgs), problem


def report(profs, q, limit, min_count=1, note=None):
    """Every profile in parallel -> (rows sorted by count desc, [incomplete notes])."""
    rows, problems = mail.each_profile(lambda p: scan(p, q, limit, note), profs, note)
    rows = [r for r in rows if r["count"] >= min_count]
    rows.sort(key=lambda r: (-r["count"], -r["ts"]))
    return rows, problems
