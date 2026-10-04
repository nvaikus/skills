"""Google Docs by path: read as markdown, targeted edits. Never rewrites a whole Doc
(that would drop comments, suggestions and formatting the markdown cannot carry)."""
from ..core.errors import CliError, UsageError
from . import drive, google, markdown


def open_doc(remote, address):
    f = drive.resolve(remote, address)
    if f.get("mimeType") != drive.DOC:
        raise UsageError(f"{drive.label(f)} is a {drive.kind(f)}, not a Google Doc"
                         + (" - .docx files are edited in the mount, not with doc edit" if f.get("name", "").endswith(".docx") else ""))
    return f


def fetch(remote, doc_id):
    return google.get(remote, f"{google.DOCS}/documents/{doc_id}", {"includeTabsContent": "true"})


def tabs(doc):
    """Flattened tabs (child tabs included) in order: [{id, title, body, lists}]."""
    out = []

    def walk(ts):
        for t in ts or []:
            dt = t.get("documentTab", {})
            p = t.get("tabProperties", {})
            out.append({"id": p.get("tabId"), "title": p.get("title"), "body": dt.get("body", {}),
                        "lists": dt.get("lists", {})})
            walk(t.get("childTabs"))

    walk(doc.get("tabs"))
    if not out:  # older shape without tabs
        out.append({"id": None, "title": None, "body": doc.get("body", {}), "lists": doc.get("lists", {})})
    return out


def pick_tab(doc, title, note):
    ts = tabs(doc)
    if title is None:
        if len(ts) > 1:
            note(f"this Doc has {len(ts)} tabs, using the first ({ts[0]['title']!r}); others: "
                 + ", ".join(repr(t["title"]) for t in ts[1:]) + " - pick one with --tab")
        return ts[0], len(ts) > 1
    hit = [t for t in ts if t["title"] == title] or [t for t in ts if (t["title"] or "").lower() == title.lower()]
    if not hit:
        raise UsageError(f"no tab {title!r}; tabs: " + ", ".join(repr(t["title"]) for t in ts))
    return hit[0], True


def cat(remote, address, tab_title, note):
    f = open_doc(remote, address)
    doc = fetch(remote, f["id"])
    tab, _ = pick_tab(doc, tab_title, note)
    return f, markdown.to_markdown(tab["body"], tab["lists"])


def _batch(remote, doc_id, reqs, revision=None):
    body = {"requests": reqs}
    if revision:
        body["writeControl"] = {"requiredRevisionId": revision}
    try:
        return google.mutate(remote, "POST", f"{google.DOCS}/documents/{doc_id}:batchUpdate", body=body) or {}
    except CliError as e:
        if e.status == 400:  # batchUpdate is atomic: a rejected batch applied nothing
            raise CliError(f"{e} - nothing was applied (batch is atomic); if the Doc changed meanwhile, rerun",
                           status=400, body=e.body) from None
        raise


def replace(remote, address, old, new, tab_title):
    f = open_doc(remote, address)
    req = {"containsText": {"text": old, "matchCase": True}, "replaceText": new}
    if tab_title:
        tab, _ = pick_tab(fetch(remote, f["id"]), tab_title, lambda m: None)
        req["tabsCriteria"] = {"tabIds": [tab["id"]]}
    res = _batch(remote, f["id"], [{"replaceAllText": req}])
    n = ((res.get("replies") or [{}])[0].get("replaceAllText") or {}).get("occurrencesChanged", 0)
    return f, n


def _end_insert(body):
    """Append point: before the final newline. lead newline unless the last paragraph is empty."""
    content = body.get("content", [])
    last = content[-1]
    at = last["endIndex"] - 1
    p = last.get("paragraph")
    empty = p is not None and "".join(e.get("textRun", {}).get("content", "") for e in p.get("elements", [])) == "\n"
    return at, not empty


def insert(remote, address, md, after, tab_title, note):
    """Append md at the end, or at the end of section `after` (before the next heading of the same
    or a higher level). -> (file, paragraphs inserted, where)."""
    blocks, warnings = markdown.parse(md)
    for w in warnings:
        note(w)
    if not blocks:
        raise UsageError("nothing to insert: the markdown is empty")
    f = open_doc(remote, address)
    doc = fetch(remote, f["id"])
    tab, explicit = pick_tab(doc, tab_title, note)
    tab_id = tab["id"] if explicit else None
    where = "end"
    at, lead, trail = None, False, False
    if after is not None:
        hs = markdown.headings(tab["body"])
        hit = [h for h in hs if h["text"] == after.strip()] or [h for h in hs if h["text"].lower() == after.strip().lower()]
        if not hit:
            raise UsageError(f"no heading {after!r} in {drive.label(f)}",
                             payload=[{"heading": "#" * max(h["level"], 1) + " " + h["text"]} for h in hs[:40]])
        if len(hit) > 1:
            raise UsageError(f"{len(hit)} headings read {after!r}; make it unique first (doc edit --replace)")
        h = hit[0]
        nxt = next((x for x in hs if x["start"] > h["start"] and x["level"] <= h["level"]), None)
        where = f"section {h['text']!r}"
        if nxt:
            at, trail = nxt["start"], True
    if at is None:
        at, lead = _end_insert(tab["body"])
    reqs = markdown.requests(blocks, at, lead, trail, tab_id)
    _batch(remote, f["id"], reqs, doc.get("revisionId"))
    return f, len(blocks), where


def new(remote, address, md, note):
    parent, name = drive.split_parent(address)
    f = drive.create_unique(remote, parent, name, drive.DOC)
    n = 0
    if md and md.strip():
        blocks, warnings = markdown.parse(md)
        for w in warnings:
            note(w)
        if blocks:
            _batch(remote, f["id"], markdown.requests(blocks, 1, False, False))
            n = len(blocks)
    return f, n
