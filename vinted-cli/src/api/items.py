"""Items: search (paged), lookup by id/URL, row + card rendering."""
import re
import urllib.parse

from ..core.errors import UsageError
from . import vinted

ROW_FIELDS = ["id", "price", "total", "cur", "brand", "size", "cond", "title", "url"]
ITEM_KEYS = ("id", "title", "url", "price")
DESC_CUT = 1500


def _amount(m):
    """{'amount': '6.00', 'currencyCode': 'EUR'} -> (6.0, 'EUR'); missing -> (None, '')."""
    if not isinstance(m, dict) or m.get("amount") in (None, ""):
        return None, ""
    try:
        return float(m["amount"]), m.get("currencyCode") or ""
    except (TypeError, ValueError):
        return None, m.get("currencyCode") or ""


def num(v):
    if v is None:
        return "?"
    return f"{v:.0f}" if float(v).is_integer() else f"{v:.2f}"


def _box(p):
    """itemBox: firstLine = brand, secondLine = 'size · condition' (size absent for size-less categories)."""
    box = p.get("itemBox") or {}
    parts = [x.strip() for x in str(box.get("secondLine") or "").split("·") if x.strip()]
    size, cond = (parts[0], parts[-1]) if len(parts) >= 2 else ("", parts[0] if parts else "")
    return box.get("firstLine") or "", size, cond


def row(it, s):
    p = vinted.need(it.get("productItem") if isinstance(it, dict) else it, ITEM_KEYS, "search item")
    price, cur = _amount(p.get("priceWithDiscount") or p["price"])
    total, _ = _amount(p.get("totalItemPrice"))
    fee, _ = _amount(p.get("serviceFee"))
    full, _ = _amount(p["price"])
    brand, size, cond = _box(p)
    user = p.get("user") or {}
    return {"id": p["id"], "price": num(price), "total": num(total) if total is not None else "", "cur": cur,
            "brand": brand, "size": size, "cond": cond, "title": (p.get("title") or "").strip(),
            "url": urllib.parse.urljoin(vinted.base(s), p["url"]),
            # -j only
            "price_value": price, "total_value": total, "fee": fee,
            "was": full if p.get("priceWithDiscount") and full != price else None,
            "promoted": bool(p.get("isPromoted")), "favourites": p.get("favouriteCount"),
            "seller_id": user.get("id"), "business": bool(user.get("isBusiness")),
            "photo": ((p.get("photos") or [{}])[0] or {}).get("url") or p.get("thumbnailUrl")}


def must_match(r, words):
    """Client-side title filter: every word (accent/case-folded) must start a word of the title."""
    if not words:
        return True
    from .categories import fold
    title = " " + re.sub(r"[^0-9a-z]+", " ", fold(r["title"])) + " "
    return all(" " + w in title for w in words)


def search(s, params, limit, must=None):
    """-> (rows, total, promoted). Pages of 96 until `limit` rows are scanned or Vinted's 10-page cap;
    ids deduplicated; `must` filters titles within the scanned rows."""
    rows, seen, promoted, total, scanned = [], set(), 0, 0, 0
    for page in range(1, vinted.MAX_PAGES + 1):
        items, pag = vinted.catalog_items(vinted.catalog_page(s, {**params, "page": page}))
        total = pag.get("total_entries") or total
        for it in items:
            if scanned >= limit:
                break
            scanned += 1
            r = row(it, s)
            if r["id"] in seen:
                continue
            seen.add(r["id"])
            if not must_match(r, must):
                continue
            promoted += r["promoted"]
            rows.append(r)
        if scanned >= limit or len(items) < vinted.PAGE or page >= (pag.get("total_pages") or 1):
            break
    return rows, total, promoted


REF = re.compile(r"^\d{4,14}$")


def lookup(ref, s):
    """id or item URL -> (flight, html, site, id)."""
    ref = ref.strip()
    if REF.match(ref):
        return (*vinted.item_page(s, ref), s, ref)
    if ref.startswith(("http://", "https://", "www.", "vinted.")):
        url = ref if ref.startswith("http") else "https://" + ref
        s = vinted.site_of_url(url)
        m = re.search(r"/items/(\d+)", urllib.parse.urlparse(url).path)
        if not m:
            raise UsageError(f"no item id in {url!r}: expected .../items/<id>-<slug>")
        return (*vinted.item_page(s, m.group(1)), s, m.group(1))
    raise UsageError(f"bad item {ref!r}: numeric id (vinted search `id` column) or a Vinted item URL")


def _plugins(fl):
    """The item page's server-driven sections: {name: data}."""
    i = 0
    while True:
        i = fl.find('"plugins":[', i)
        if i < 0:
            raise vinted.Broken("Vinted item page changed: no plugins list (attributes, description, seller)")
        try:
            lst = vinted.extract(fl[i:], '"plugins":', "item plugins")
        except vinted.Broken:
            lst = None
        if isinstance(lst, list) and lst and all(isinstance(x, dict) and "name" in x for x in lst):
            return {x["name"]: x.get("data") or {} for x in lst}
        i += 10


def details(fl, html, s, item_id):
    """-> flat dict of everything the card shows (also the -j payload)."""
    pl = _plugins(fl)
    attrs = {a.get("code"): a.get("data") or {} for a in (pl.get("attributes") or {}).get("attributes") or []
             if isinstance(a, dict)}
    ps = vinted.extract(fl, '"pricingServices":', "pricing", default={})
    svc = ps.get("services") or {}
    price, cur = _amount(ps.get("originalAskingAmount"))
    fee, _ = _amount((svc.get("buyerProtection") or {}).get("finalPrice"))
    total, _ = _amount(ps.get("totalAmount"))
    ship = svc.get("shipping") or {}
    ship_from, _ = _amount(ship.get("finalPrice"))
    ship_orig, _ = _amount(ship.get("originalPrice"))
    ld = vinted.ld_json(html)
    offer = ld.get("offers") or {}
    if price is None and offer.get("price") is not None:
        price, cur = float(offer["price"]), offer.get("priceCurrency") or ""
    user = pl.get("user_info_header") or {}
    rep = user.get("feedback_reputation")
    status = pl.get("ask_seller") or {}
    photos = [p.get("url") for p in (pl.get("make_offer") or {}).get("photos") or [] if isinstance(p, dict)]
    cat = re.search(r'"catalog_id":"(\d+)","item_id":"' + re.escape(str(item_id)) + '"', fl)
    title = ld.get("name") or next((e.get("value") for ln in (pl.get("summary") or {}).get("lines") or []
                                   for e in ln.get("elements") or [] if e.get("style") == "title"), "")
    if not title and not attrs:
        raise vinted.Broken("Vinted item page changed: no title and no attributes")
    state = "reserved" if status.get("is_reserved") else "hidden" if status.get("is_hidden") else \
        "available" if status.get("can_buy") else (offer.get("availability") or "?")
    return {"id": int(item_id), "site": s, "title": title, "price": price, "currency": cur,
            "buyer_protection": fee, "total": total, "shipping_from": ship_from, "shipping_full": ship_orig,
            "brand": (attrs.get("brand") or {}).get("value"), "brand_id": (attrs.get("brand") or {}).get("id"),
            # the page's size/status ids are another id space than the search filters': not exposed
            "size": (attrs.get("size") or {}).get("value"), "condition": (attrs.get("status") or {}).get("value"),
            "color": (attrs.get("color") or {}).get("value"), "uploaded": (attrs.get("upload_date") or {}).get("value"),
            "category": ld.get("category"), "category_id": int(cat.group(1)) if cat else None,
            "state": state, "seller": user.get("name"), "business": bool(user.get("business")),
            "rating": round(rep * 5, 1) if isinstance(rep, (int, float)) and user.get("feedback_count") else None,
            "reviews": user.get("feedback_count"), "photos": photos,
            "description": (pl.get("description") or {}).get("description") or ld.get("description") or "",
            "url": offer.get("url") or f"{vinted.base(s)}/items/{item_id}"}


def card(d, full=False):
    cur = d["currency"] or ""
    price = f"{num(d['price'])} {cur}".strip()
    if d["total"] is not None:
        price += f" · {num(d['total'])} {cur} with buyer protection".rstrip()
        if d["buyer_protection"] is not None:
            price += f" (fee {num(d['buyer_protection'])})"
    if d["shipping_from"] is not None:
        ship = f"from {num(d['shipping_from'])} {cur}"
        if d["shipping_full"] not in (None, d["shipping_from"]):
            ship += f" (usually {num(d['shipping_full'])})"
    else:
        ship = "?"
    seller = d["seller"] or "?"
    bits = ["business" if d["business"] else "private"]
    if d["rating"] is not None:
        bits.append(f"{d['rating']}/5 from {d['reviews']} reviews")
    else:
        bits.append("no reviews yet")
    lines = [f"# {d['title']}", "",
             f"- price: {price}",
             f"- shipping: {ship}",
             f"- brand: {d['brand'] or '-'} · size: {d['size'] or '-'} · condition: {d['condition'] or '-'}"
             f" · color: {d['color'] or '-'}",
             f"- category: {d['category'] or '?'} (id {d['category_id'] or '?'})",
             f"- uploaded: {d['uploaded'] or '?'} · {d['state']}",
             f"- seller: {seller} ({', '.join(bits)})",
             f"- id: {d['id']} · {d['url']}",
             f"- photos ({len(d['photos'])}):"] + [f"  - {u}" for u in d["photos"][:None if full else 4]]
    if not full and len(d["photos"]) > 4:
        lines.append(f"  - … +{len(d['photos']) - 4} more (--full)")
    desc = re.sub(r"\n\s*\n+", "\n\n", "\n".join(x.strip() for x in d["description"].splitlines())).strip()
    if desc:
        cut = not full and len(desc) > DESC_CUT
        lines += ["", "## Description", desc[:DESC_CUT].rstrip() + " … (cut: --full)" if cut else desc]
    return "\n".join(lines) + "\n"
