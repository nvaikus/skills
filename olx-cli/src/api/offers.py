"""Offers: search (paged, promoted dropped), lookup by id/URL, row + card rendering."""
import re

from ..core.errors import UsageError
from . import olx

ROW_FIELDS = ["id", "price", "cur", "was", "title", "city", "date", "url"]
OFFER_KEYS = ("id", "url", "title", "params", "location", "created_time", "last_refresh_time")
DESC_CUT = 1500


def price_of(o):
    """-> dict(value, kind, currency, negotiable, previous, text). kind: price | arranged | exchange | free |
    budget | none. value is a number only for price/arranged (the comparable kinds)."""
    p = next((x for x in o.get("params") or [] if isinstance(x, dict) and x.get("key") == "price"), None)
    v = (p or {}).get("value") or {}
    kind = v.get("type") or ("none" if p is None else "price")
    num = v.get("value") if kind in ("price", "arranged") else None
    prev = v.get("previous_value")
    text = {"exchange": "swap", "free": "free", "budget": "ask", "none": "-"}.get(kind)
    if text is None:
        text = _num(num) + (" neg" if v.get("negotiable") or kind == "arranged" else "")
    return {"value": num, "kind": kind, "currency": v.get("currency"), "negotiable": bool(v.get("negotiable")),
            "previous": prev, "text": text}


def _num(v):
    if v is None:
        return "?"
    return f"{v:.0f}" if float(v).is_integer() else f"{v:.2f}"


def _param(o, key):
    p = next((x for x in o.get("params") or [] if isinstance(x, dict) and x.get("key") == key), None)
    v = (p or {}).get("value")
    return v.get("key") if isinstance(v, dict) else v


def row(o):
    olx.need(o, OFFER_KEYS, "offer")
    pr = price_of(o)
    loc = o.get("location") or {}
    user = o.get("user") or {}
    return {"id": o["id"], "price": pr["text"], "cur": pr["currency"] if pr["value"] is not None else "",
            "was": _num(pr["previous"]) if pr["previous"] is not None else "",
            "title": (o.get("title") or "").strip(), "city": (loc.get("city") or {}).get("name"),
            "date": (o.get("last_refresh_time") or "")[:10], "url": o["url"],
            # -j only
            "price_value": pr["value"], "price_kind": pr["kind"], "negotiable": pr["negotiable"],
            "region": (loc.get("region") or {}).get("name"), "created": o.get("created_time"),
            "refreshed": o.get("last_refresh_time"), "category_id": (o.get("category") or {}).get("id"),
            "condition": _param(o, "state"), "business": bool(o.get("business")),
            "seller": user.get("name"), "seller_id": user.get("id"), "photos": len(o.get("photos") or []),
            "courier": bool((o.get("contact") or {}).get("courier"))}


def must_match(r, words):
    """Client-side title filter: every word (accent/case-folded) must start a word of the title."""
    if not words:
        return True
    from .categories import fold
    title = " " + re.sub(r"[^0-9a-z]+", " ", fold(r["title"])) + " "
    return all(" " + w in title for w in words)


def search(s, params, limit, must=None):
    """-> (rows, total, promoted_skipped). Scans `limit` organic rows in pages of 50; promoted top ads
    (prepended, ignore sort) are dropped; ids deduplicated; `must` filters titles within the scanned rows."""
    rows, seen, promoted, total, offset = [], set(), 0, 0, 0
    while offset < limit and offset <= olx.WINDOW:
        page = min(olx.PAGE, limit - offset)
        body = olx.offers(s, {**params, "offset": offset, "limit": page})
        meta = body.get("metadata") or {}
        total = meta.get("visible_total_count") or meta.get("total_elements") or 0
        promo = set(((meta.get("source") or {}).get("promoted")) or meta.get("promoted") or [])
        data = body["data"]
        for i, o in enumerate(data):
            if i in promo:
                promoted += 1
                continue
            r = row(o)
            if not must_match(r, must):
                continue
            if r["id"] not in seen:
                seen.add(r["id"])
                rows.append(r)
        organic = len(data) - len(promo & set(range(len(data))))
        if organic < page:
            break
        offset += page
    return rows[:limit], total, promoted


REF = re.compile(r"^\d{5,12}$")


def lookup(ref, s):
    """id or listing URL -> (offer, site)."""
    ref = ref.strip()
    if REF.match(ref):
        return olx.offer(s, ref), s
    if ref.startswith(("http://", "https://", "www.", "olx.")):
        url = ref if ref.startswith("http") else "https://" + ref
        s = olx.site_of_url(url)
        m = re.search(r"[?&]ad[-_]id=(\d+)", url)
        return olx.offer(s, m.group(1) if m else olx.id_from_page(url)), s
    raise UsageError(f"bad listing {ref!r}: numeric id (olx search `id` column) or an OLX listing URL")


def card(o, full=False):
    r = row(o)
    pr = price_of(o)
    loc, user, contact = o.get("location") or {}, o.get("user") or {}, o.get("contact") or {}
    price = pr["text"] if pr["value"] is None else f"{pr['text']} {pr['currency'] or ''}".strip()
    if pr["previous"] is not None:
        price += f" (was {_num(pr['previous'])})"
    seller = f"{user.get('name') or '?'} ({'business' if o.get('business') else 'private'}"
    seller += f", on OLX since {(user.get('created') or '')[:7]}" if user.get("created") else ""
    seller += f", last seen {(user.get('last_seen') or '')[:10]}" if user.get("last_seen") else ""
    seller += ")"
    reach = ", ".join(k for k in ("chat", "phone", "courier") if contact.get(k)) or "-"
    photos = o.get("photos") or []
    lines = [f"# {r['title']}", "",
             f"- price: {price}",
             f"- where: {r['city'] or '?'}, {r['region'] or '?'}",
             f"- posted: {(o.get('created_time') or '')[:16].replace('T', ' ')} · refreshed "
             f"{(o.get('last_refresh_time') or '')[:16].replace('T', ' ')} · valid to {(o.get('valid_to_time') or '')[:10]}"
             f" · status {o.get('status') or '?'}",
             f"- seller: {seller}",
             f"- contact: {reach}",
             f"- photos: {len(photos)}" + (f" · first {photos[0]['link'].replace('{width}x{height}', '1024x768')}"
                                           if photos and photos[0].get("link") else ""),
             f"- id: {o['id']} · category {r['category_id']}",
             f"- url: {o['url']}"]
    params = [p for p in o.get("params") or [] if isinstance(p, dict) and p.get("key") != "price"]
    if params:
        lines += ["", "## Params"]
        for p in params:
            v = p.get("value")
            label = v.get("label") if isinstance(v, dict) else v
            lines.append(f"- {p.get('name') or p.get('key')}: {label}")
    desc = re.sub(r"<br\s*/?>", "\n", o.get("description") or "")
    desc = re.sub(r"<[^>]+>", "", desc)
    desc = re.sub(r"\n\s*\n+", "\n\n", "\n".join(x.strip() for x in desc.splitlines())).strip()
    if desc:
        cut = not full and len(desc) > DESC_CUT
        lines += ["", "## Description", desc[:DESC_CUT].rstrip() + " … (cut: --full)" if cut else desc]
    return "\n".join(lines) + "\n"
