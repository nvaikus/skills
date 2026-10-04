"""List-Unsubscribe (RFC 2369) and one-click (RFC 8058). The one-click POST goes to the sender's
own server, not Google: the third allow_mutate caller next to google.mutate and auth."""
import re
import urllib.parse

from ..core import http
from ..core.errors import CliError, UsageError
from . import compose, google, mail

HEADERS = ["From", "Subject", "List-Unsubscribe", "List-Unsubscribe-Post"]
SCAN = 10  # newest messages of a sender searched for one carrying the header


def links(h):
    """Message headers (lowercase keys) -> {one_click, mailto, url} (None when absent)."""
    raw = h.get("list-unsubscribe", "") or ""
    found = re.findall(r"<\s*([^>]+?)\s*>", raw) or [x.strip() for x in raw.split(",") if x.strip()]
    mailto = next((x for x in found if x.lower().startswith("mailto:")), None)
    url = next((x for x in found if x.lower().startswith(("https://", "http://"))), None)
    post = "list-unsubscribe=one-click" in (h.get("list-unsubscribe-post", "") or "").lower().replace(" ", "")
    one = url if post and url and url.lower().startswith("https://") else None
    return {"one_click": one, "mailto": mailto, "url": url}


def kind(h):
    lk = links(h)
    return "one-click" if lk["one_click"] else "mailto" if lk["mailto"] else "url" if lk["url"] else "-"


def _meta(prof, mid):
    return google.get(prof, f"/messages/{mid}", {"format": "metadata", "metadataHeaders": HEADERS})


def plan(prof, target):
    """A sender address (its newest message carrying the header) or a message id -> plan dict."""
    if "@" in target:
        addr = target.strip().lower()
        ids = mail.list_ids(prof, f"from:{addr}", SCAN)
        if not ids:
            raise UsageError(f"profile {prof!r}: no mail from {addr}")
        msgs = [_meta(prof, i) for i in ids]
        m = next((x for x in msgs if kind(mail.headers(x.get("payload"))) != "-"), msgs[0])
    else:
        m = _meta(prof, target)
    h = mail.headers(m.get("payload"))
    return {"profile": prof, "target": target, "message_id": m["id"], "sender": mail.short_addr(h.get("from")),
            "method": kind(h), **links(h)}


def _mailto(prof, link):
    """mailto:addr?subject=..&body=.. -> sent message id (through the normal send path)."""
    u = urllib.parse.urlsplit(link)
    q = {k.lower(): v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
    to = urllib.parse.unquote(u.path) or q.get("to", "")
    if not to:
        raise UsageError(f"mailto link without an address: {link}")
    msg = compose.build(to=to, subject=q.get("subject") or "unsubscribe", body=q.get("body") or "unsubscribe")
    return (compose.send(prof, msg) or {}).get("id", "")


def safe_url(url):
    """Header URLs may carry raw spaces/control chars (LinkedIn); http.client refuses them."""
    return urllib.parse.quote(url.strip(), safe=":/?#[]@!$&'()*+,;=%~")


def _post(url):
    http.request("POST", safe_url(url), data=b"List-Unsubscribe=One-Click", content_type="application/x-www-form-urlencoded",
                 allow_mutate=True, retries=1, timeout=30)


def execute(p, dry_run=False):
    """Plan -> {**plan, result, ok}. one-click POST, else mailto through send, else the URL as manual."""
    out = dict(p)
    if p["method"] == "-":
        return {**out, "ok": True, "result": "no List-Unsubscribe header: filter it instead "
                                             "(gmail filter create --from ADDR --archive)"}
    if p["method"] == "url":
        return {**out, "method": "manual", "ok": True, "result": p["url"]}
    if dry_run:
        what = f"would POST {p['one_click']}" if p["method"] == "one-click" else f"would mail {p['mailto']}"
        return {**out, "ok": True, "result": what}
    prefix = ""
    if p["method"] == "one-click":
        try:
            _post(p["one_click"])
            return {**out, "ok": True, "result": "done"}
        except CliError as e:
            if not p["mailto"]:
                return {**out, "ok": False, "result": f"failed: {e}" + (f"; by hand: {p['url']}" if p["url"] else "")}
            prefix = f"one-click failed ({e}); "
    try:
        mid = _mailto(p["profile"], p["mailto"])
        return {**out, "method": "mailto", "ok": True, "result": f"{prefix}sent {mid}"}
    except CliError as e:
        return {**out, "method": "mailto", "ok": False, "result": f"{prefix}failed: {e}"}
