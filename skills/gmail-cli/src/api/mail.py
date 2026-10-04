"""Gmail nouns: labels, message/thread lookup, search rows, bulk modify, trash. Profile-explicit."""
import concurrent.futures as cf
import difflib
import html
import threading
from datetime import datetime
from email.utils import parseaddr

from ..core.errors import CliError, UsageError
from . import google

SYSTEM = {"INBOX", "UNREAD", "STARRED", "IMPORTANT", "SENT", "DRAFT", "SPAM", "TRASH", "CHAT",
          "CATEGORY_PERSONAL", "CATEGORY_SOCIAL", "CATEGORY_PROMOTIONS", "CATEGORY_UPDATES", "CATEGORY_FORUMS"}
META_HEADERS = ["From", "To", "Cc", "Subject", "Date"]
LIST_PAGE = 500
BATCH = 1000  # batchModify limit

_labels = {}
_plocks = {}
_lock = threading.Lock()


pmap = google.pmap


def mailbox(prof):
    """users.getProfile: emailAddress, messagesTotal, threadsTotal."""
    return google.get(prof, "/profile") or {}


# ---- labels -------------------------------------------------------------------------------------

def labels(prof, fresh=False):
    """-> [label dicts] (process cache per profile)."""
    with _lock:  # per-profile lock: one global lock held over HTTP serialized every profile's fetch
        plock = _plocks.setdefault(prof, threading.Lock())
    with plock:
        if fresh or prof not in _labels:
            _labels[prof] = (google.get(prof, "/labels") or {}).get("labels", [])
        return _labels[prof]


def forget_labels(prof):
    with _lock:
        _labels.pop(prof, None)


def label_names(prof):
    return {lb["id"]: lb["name"] for lb in labels(prof)}


def show_label(lid, names):
    name = names.get(lid, lid)
    return name[len("CATEGORY_"):] if name.startswith("CATEGORY_") else name


def find_label(prof, name, must=True):
    """Label by name (case-insensitive), id, or system name (INBOX, PROMOTIONS = CATEGORY_PROMOTIONS)."""
    labs = labels(prof)
    key = name.strip()
    up = key.upper()
    for cand in (up, "CATEGORY_" + up):
        if cand in SYSTEM:
            return next((lb for lb in labs if lb["id"] == cand), {"id": cand, "name": cand, "type": "system"})
    for lb in labs:
        if lb["id"] == key or lb["name"] == key:
            return lb
    hits = [lb for lb in labs if lb["name"].lower() == key.lower()]
    if len(hits) == 1:
        return hits[0]
    if not must:
        return None
    close = difflib.get_close_matches(key, [lb["name"] for lb in labs], n=4, cutoff=0.5)
    raise UsageError(f"no label {name!r} in profile {prof!r}" + (f"; close: {', '.join(close)}" if close else "")
                     + f" - `gmail --profile {prof} label list`")


# ---- rows ---------------------------------------------------------------------------------------

def when(ms):
    try:
        return datetime.fromtimestamp(int(ms) / 1000).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return ""


def headers(payload):
    out = {}
    for h in (payload or {}).get("headers", []):
        out.setdefault(h["name"].lower(), h["value"])
    return out


def short_addr(value):
    name, addr = parseaddr(value or "")
    if name and addr:
        return f"{name} <{addr}>"
    return addr or (value or "")


def row(prof, msg, names, extra=None):
    h = headers(msg.get("payload"))
    r = {"profile": prof, "id": msg["id"], "thread_id": msg.get("threadId"), "date": when(msg.get("internalDate")),
         "from": short_addr(h.get("from")), "to": h.get("to", ""), "subject": h.get("subject", ""),
         "labels": ",".join(show_label(x, names) for x in msg.get("labelIds", [])),
         "snippet": html.unescape(msg.get("snippet") or "")[:140], "ts": int(msg.get("internalDate") or 0)}
    r.update(extra or {})
    return r


def meta(prof, mid):
    return google.get(prof, f"/messages/{mid}", {"format": "metadata", "metadataHeaders": META_HEADERS})


def list_refs(prof, q, limit=None, threads=False, spam_trash=False, label_ids=None):
    """[{id, threadId}] matching a Gmail query (newest first). limit None = all."""
    kind = "threads" if threads else "messages"
    out, token = [], None
    while True:
        want = LIST_PAGE if limit is None else min(LIST_PAGE, limit - len(out))
        params = {"maxResults": want}
        if q:
            params["q"] = q
        if spam_trash:
            params["includeSpamTrash"] = "true"
        if label_ids:
            params["labelIds"] = label_ids
        if token:
            params["pageToken"] = token
        got = google.get(prof, f"/{kind}", params) or {}
        out += got.get(kind, [])
        token = got.get("nextPageToken")
        if not token or (limit is not None and len(out) >= limit):
            return out[:limit] if limit is not None else out


def list_ids(prof, q, limit=None, threads=False, spam_trash=False, label_ids=None):
    """Ids matching a Gmail query (newest first). limit None = all."""
    return [r["id"] for r in list_refs(prof, q, limit, threads, spam_trash, label_ids)]


def incomplete(prof, got, total, err):
    return f"profile {prof}: incomplete - {got} of {total} fetched, then: {err}"


def search_one(prof, q, limit, threads=False, spam_trash=False):
    """-> (rows, problem or None). A failure partway keeps the rows already fetched."""
    names = label_names(prof)
    ids = list_ids(prof, q, limit, threads, spam_trash)
    if not threads:
        msgs, err = google.pmap_partial(lambda i: meta(prof, i), ids)
        return [row(prof, m, names) for m in msgs], (incomplete(prof, len(msgs), len(ids), err) if err else None)

    def thread_row(tid):
        t = google.get(prof, f"/threads/{tid}", {"format": "metadata", "metadataHeaders": META_HEADERS})
        msgs = t.get("messages", [])
        last = msgs[-1]
        labs = {x for m in msgs for x in m.get("labelIds", [])}
        r = row(prof, {**last, "labelIds": sorted(labs)}, names, {"count": len(msgs)})
        r["subject"] = headers(msgs[0].get("payload")).get("subject", r["subject"])
        return r
    rows, err = google.pmap_partial(thread_row, ids)
    return rows, (incomplete(prof, len(rows), len(ids), err) if err else None)


def each_profile(fn, profs, note=None):
    """fn(prof) -> (rows, problem) on every profile in parallel -> (rows, problems). A profile that
    fails outright is skipped with a note; all failing -> the first error."""
    if len(profs) == 1:
        rows, problem = fn(profs[0])
        return rows, [problem] if problem else []
    rows, problems, errors = [], [], []
    with cf.ThreadPoolExecutor(max_workers=len(profs)) as ex:
        futs = {ex.submit(fn, p): p for p in profs}
        for f in cf.as_completed(futs):
            try:
                got, problem = f.result()
                rows += got
                if problem:
                    problems.append(problem)
            except CliError as e:
                errors.append((futs[f], e))
    if errors and len(errors) == len(profs):
        raise errors[0][1]
    for p, e in sorted(errors, key=lambda x: x[0]):
        if note:
            note(f"profile {p} skipped: {e}")
    return rows, sorted(problems)


def search(profs, q, limit, threads=False, spam_trash=False, note=None):
    """Every profile in parallel -> (rows merged newest first and cut to limit, [incomplete notes])."""
    rows, problems = each_profile(lambda p: search_one(p, q, limit, threads, spam_trash), profs, note)
    rows.sort(key=lambda r: r["ts"], reverse=True)
    return rows[:limit], problems


# ---- one message / thread -----------------------------------------------------------------------

def message(prof, mid, fmt="full"):
    return google.get(prof, f"/messages/{mid}", {"format": fmt})


def thread_of(prof, any_id, fmt="full"):
    """A thread by thread id, or the thread of a message id."""
    try:
        return google.get(prof, f"/threads/{any_id}", {"format": fmt})
    except UsageError as e:
        if e.status not in (400, 404):
            raise
    tid = message(prof, any_id, "minimal")["threadId"]
    return google.get(prof, f"/threads/{tid}", {"format": fmt})


def attachment_data(prof, mid, part):
    """Bytes of an attachment part (inline data, or fetched by its attachmentId)."""
    from .render import b64
    body = part.get("body") or {}
    if body.get("attachmentId"):
        body = google.get(prof, f"/messages/{mid}/attachments/{body['attachmentId']}") or {}
    return b64(body.get("data"))


def exists(prof, any_id):
    for path in (f"/messages/{any_id}", f"/threads/{any_id}"):
        try:
            google.get(prof, path, {"format": "minimal"})
            return True
        except UsageError as e:
            if e.status not in (400, 404):
                raise
    return False


def locate(any_id, profs):
    """The profile that holds a message/thread id (ids are per account). Tries profs in order."""
    for p in profs:
        try:
            if exists(p, any_id):
                return p
        except UsageError:
            continue  # a logged-out profile cannot hold what we look for
    raise UsageError(f"id {any_id} not found in any profile ({', '.join(profs)}): ids come from `gmail search`")


# ---- bulk changes -------------------------------------------------------------------------------

def thread_messages(prof, ids):
    """Message ids of the whole threads containing ids (each a message or thread id)."""
    out = []
    for t in google.pmap(lambda i: thread_of(prof, i, "minimal"), ids):
        out += [m["id"] for m in t.get("messages", [])]
    return list(dict.fromkeys(out))


def batch_modify(prof, ids, add=(), remove=()):
    for i in range(0, len(ids), BATCH):
        google.mutate(prof, "POST", "/messages/batchModify",
                      {"ids": ids[i:i + BATCH], "addLabelIds": list(add), "removeLabelIds": list(remove)})
    return len(ids)


def trash(prof, ids, undo=False):
    verb = "untrash" if undo else "trash"
    google.pmap(lambda i: google.mutate(prof, "POST", f"/messages/{i}/{verb}"), ids)
    return len(ids)


# ---- label changes ------------------------------------------------------------------------------

def create_label(prof, name):
    """Create name and any missing parents (Gmail nests by 'A/B' names). -> [created label dicts]."""
    made, parts = [], [p.strip() for p in name.split("/")]
    if any(not p for p in parts):
        raise UsageError(f"bad label name {name!r}: empty part between slashes")
    for i in range(1, len(parts) + 1):
        sub = "/".join(parts[:i])
        if find_label(prof, sub, must=False):
            continue
        made.append(google.mutate(prof, "POST", "/labels", {"name": sub, "labelListVisibility": "labelShow",
                                                            "messageListVisibility": "show"}))
        forget_labels(prof)
    return made


def label_details(prof, labs):
    """labels.get per label (the list call carries no counts)."""
    return google.pmap(lambda lb: google.get(prof, f"/labels/{lb['id']}"), labs)


def user_label(prof, name):
    lb = find_label(prof, name)
    if lb.get("type") == "system":
        raise UsageError(f"{lb['name']} is a system label: it cannot be renamed or deleted")
    return lb


def rename_label(prof, old, new):
    """Rename old and every nested 'old/...' label. -> [(old name, new name)]."""
    lb = user_label(prof, old)
    if find_label(prof, new, must=False):
        raise UsageError(f"label {new!r} already exists")
    base = lb["name"]
    moves = [(x, new + x["name"][len(base):]) for x in labels(prof)
             if x.get("type") != "system" and (x["name"] == base or x["name"].startswith(base + "/"))]
    if "/" in new:
        parent = new.rsplit("/", 1)[0]
        if not find_label(prof, parent, must=False):
            create_label(prof, parent)
    for x, to in sorted(moves, key=lambda m: len(m[0]["name"])):
        google.mutate(prof, "PATCH", f"/labels/{x['id']}", {"name": to})
    forget_labels(prof)
    return [(x["name"], to) for x, to in moves]


def delete_label(prof, name):
    lb = user_label(prof, name)
    google.mutate(prof, "DELETE", f"/labels/{lb['id']}")
    forget_labels(prof)
    return lb
