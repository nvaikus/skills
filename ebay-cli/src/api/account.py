"""Cart and seller messages in the user's logged-in browser (api/browser): ids in, rows out.
Scope is fixed: add/list/remove cart lines, send/read seller messages. Never checkout, pay, bid or offer."""
from ..core.errors import CliError, UsageError, Waiting
from . import browse, browser, markets

# "<who>: <day> <time> <text>" labels a message; the user's own messages are labelled with "you" in the
# site language (live 2026-10 ebay.de: "Sie")
ME = {"sie", "you", "du", "vous", "tu", "usted", "voi", "lei", "jij", "u", "ty", "wy", "jy"}
MAX_TEXT = 2000


def ref_id(ref):
    """id | URL (?var=) | v1|id|var -> (legacy id, variation id or None)."""
    k = browse.parse_ref(ref)
    if k[0] == "rest":
        parts = k[1].split("|")
        if len(parts) < 2 or not parts[1].isdigit():
            raise UsageError(f"not an eBay item id: {ref!r}")
        return parts[1], (parts[2] if len(parts) > 2 and parts[2] not in ("", "0") else None)
    return k[1], k[2]


def variation_id(item_id, spec, loc):
    """--variation: a variation id as is, or Name=Value[,Name=Value] matched against Browse variations."""
    if not spec:
        return None
    spec = spec.strip()
    if spec.isdigit():
        return spec
    want = {}
    for pair in spec.split(","):
        if "=" not in pair:
            raise UsageError(f"--variation {spec!r}: a variation id or Name=Value[,Name=Value] (see ebay item {item_id})")
        k, v = pair.split("=", 1)
        want[k.strip().lower()] = v.strip().lower()
    _, variations = browse.lookup(item_id, loc)
    if not variations:
        raise UsageError(f"listing {item_id} has no variations: drop --variation")

    def aspects(v):
        return {str(k).lower(): str(x).lower() for k, x in browse._aspects(v).items()}

    hits = [v for v in variations if all(aspects(v).get(k) == x for k, x in want.items())]
    if len(hits) != 1:
        raise UsageError(f"--variation {spec!r} matches {len(hits)} of {len(variations)} variations: "
                         f"pick one id from `ebay item {item_id}`")
    return hits[0]["itemId"].split("|")[2]


def login(cfg, market=None):
    r = browser.run(cfg, "login", {}, market)
    if not r.get("logged_in"):
        raise Waiting(f"log in to eBay in the Chrome window that just opened (browser session "
                      f"'{browser.session(cfg)}'){browser.view_hint(cfg)}, then rerun `ebay login`")
    return {"logged_in": True, "session": browser.session(cfg), "site": browser.domain(cfg, market)}


def cart_list(cfg, market=None):
    return browser.run(cfg, "cart_list", {}, market)["lines"]


def cart_add(cfg, item_id, var=None, qty=None, market=None):
    if qty is not None and qty < 1:
        raise UsageError("--qty must be 1 or more")
    r = browser.run(cfg, "cart_add", {"id": item_id, "var": var, "qty": qty}, market)
    lines = r.get("lines") or []
    return {"id": item_id, "added": bool(r.get("added")), "already": bool(r.get("already")),
            "qty": sum(int(x.get("qty") or 1) for x in lines), "lines": len(lines),
            "price": lines[0].get("price") if lines else None, "variation": var,
            "title": lines[0].get("title") if lines else None}


def cart_rm(cfg, ids, market=None):
    r = browser.run(cfg, "cart_rm", {"ids": ids}, market)
    return r["results"], r.get("lines") or []


def message_text(text, stdin):
    if text in (None, "-"):
        if stdin.isatty():
            raise UsageError('message text missing: ebay msg send ID "text" (or pipe it on stdin)')
        text = stdin.read()
    text = text.strip()
    if not text:
        raise UsageError("message text is empty")
    if len(text) > MAX_TEXT:
        raise UsageError(f"message is {len(text)} chars; eBay member messages take at most {MAX_TEXT}")
    return text


def _from(who, seller):
    w = (who or "").strip()
    if w.lower() in ME:
        return "me"
    return w or "?"


def seller_of(cfg, item_id, market=None):
    """Seller user id from the Browse API (the listing page shows store slugs). None -> the page fallback."""
    try:
        loc = {"market": markets.norm(market) or markets.norm(cfg.get("market")) or markets.FALLBACK}
        return ((browse.lookup(item_id, loc)[0] or {}).get("seller") or {}).get("username")
    except CliError:
        return None


def msg_send(cfg, item_id, text, seller=None, market=None):
    seller = seller or seller_of(cfg, item_id, market)
    r = browser.run(cfg, "msg_send", {"id": item_id, "text": text, "seller": seller}, market)
    m = r["message"]
    return {"id": item_id, "seller": r.get("seller"), "from": _from(m.get("who"), r.get("seller")),
            "day": m.get("day"), "time": m.get("time"), "text": m.get("text"), "messages": r.get("count")}


def msg_thread(cfg, item_id, seller=None, market=None):
    seller = seller or seller_of(cfg, item_id, market)
    r = browser.run(cfg, "msg_list", {"id": item_id, "seller": seller}, market)
    return r.get("seller"), [{"id": item_id, "from": _from(m.get("who"), r.get("seller")), "day": m.get("day"),
                              "time": m.get("time"), "text": m.get("text"), "translated": bool(m.get("translated")),
                              "original": m.get("original")} for m in r.get("messages") or []]


def msg_inbox(cfg, limit=25, market=None):
    return browser.run(cfg, "msg_list", {"id": None, "limit": limit}, market)["rows"]
