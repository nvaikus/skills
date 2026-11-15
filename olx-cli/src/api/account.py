"""Login check and seller chat in the user's logged-in browser (api/browser): refs in, rows out.
Scope is fixed: sign-in, read conversations, send a chat message. Never posts, buys or pays."""
from ..core.errors import UsageError, Waiting
from . import browser, offers, olx

MAX_TEXT = 5000  # chat bundle 2026-11: "You can only write up to 5000 characters per message"


def login(cfg, s):
    r = browser.run(cfg, "login", {}, olx.SITES[s])
    if not r.get("logged_in"):
        raise Waiting(f"sign in to OLX in the Chrome window (browser session '{browser.session(cfg)}'): its sign-in page"
                      f" is open{browser.view_hint(cfg)}; email + password or Google/Apple/Facebook. Then rerun `olx login`")
    return {"logged_in": True, "session": browser.session(cfg), "site": olx.SITES[s]}


def listing(ref, s):
    """id | URL -> (offer, site). The page needs the listing URL; chat-disabled listings fail before the browser."""
    o, s = offers.lookup(ref, s)
    if not (o.get("contact") or {}).get("chat", True):
        raise UsageError(f"listing {o.get('id')}: the seller does not take OLX chat messages (phone only: olx show {o.get('id')})")
    return o, s


def message_text(text, stdin):
    if text in (None, "-"):
        if stdin.isatty():
            raise UsageError('message text missing: olx msg send ID "text" (or pipe it on stdin)')
        text = stdin.read()
    text = text.strip()
    if not text:
        raise UsageError("message text is empty")
    if len(text) > MAX_TEXT:
        raise UsageError(f"message is {len(text)} chars; OLX chat takes at most {MAX_TEXT}")
    return text


def _who(m, seller):
    if m.get("mine"):
        return "me"
    return seller or m.get("who") or "?"


def msg_send(cfg, ref, text, s):
    o, s = listing(ref, s)
    r = browser.run(cfg, "msg_send", {"id": o["id"], "url": o["url"], "text": text}, olx.SITES[s])
    m = r["message"]
    return {"id": o["id"], "seller": (o.get("user") or {}).get("name"), "conversation": r.get("conversation"),
            "time": m.get("time"), "text": m.get("text"), "messages": r.get("count")}


def msg_thread(cfg, s, ref=None, conversation=None):
    o, seller = {}, None
    if ref:
        o, s = listing(ref, s)
        seller = (o.get("user") or {}).get("name")
    r = browser.run(cfg, "msg_list", {"id": o.get("id"), "url": o.get("url"), "conversation": conversation}, olx.SITES[s])
    conv = r.get("conversation") or conversation
    return conv, [{"conversation": conv, "from": _who(m, seller), "time": m.get("time"), "text": m.get("text"),
                   "label": m.get("who")} for m in r.get("messages") or []]


def msg_inbox(cfg, s, limit=25):
    if limit < 1:
        raise UsageError("--limit must be 1 or more")
    return browser.run(cfg, "msg_list", {"id": None, "conversation": None, "limit": limit}, olx.SITES[s])["rows"]
