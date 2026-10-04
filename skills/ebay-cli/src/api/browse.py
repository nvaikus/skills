"""Browse API: search rows, item lookup (RESTful id, legacy id, URL, multi-variation) and the item card."""
import html
import re
import urllib.parse

from ..core.errors import CliError, UsageError
from ..core import http
from . import ebay, markets

DESC_MAX = 1500
BUY_SHORT = {"FIXED_PRICE": "fixed", "AUCTION": "auction", "BEST_OFFER": "offer", "CLASSIFIED_AD": "classified"}


def _money(m):
    if not m or m.get("value") is None:
        return None, None
    return float(m["value"]), m.get("currency")


def _fmt(v, cur=None):
    return "" if v is None else f"{v:.2f}" + (f" {cur}" if cur else "")


def _when(iso):
    return (iso or "")[:16].replace("T", " ") + ("Z" if iso else "")


def ship_of(s):
    """-> (value or None, currency). None = eBay gave no cost (does not ship there, or calculated w/o zip)."""
    opts = s.get("shippingOptions") or []
    costs = [_money(o.get("shippingCost")) for o in opts if o.get("shippingCost")]
    costs = [c for c in costs if c[0] is not None]
    return min(costs) if costs else (None, None)


def legacy_of(item_id):
    parts = (item_id or "").split("|")
    return parts[1] if len(parts) > 1 else None


def row(s, market):
    price, cur = _money(s.get("currentBidPrice") or s.get("price"))
    ship, _ = ship_of(s)
    opts = s.get("buyingOptions") or []
    buy = "+".join(BUY_SHORT.get(o, o.lower()) for o in opts)
    if "AUCTION" in opts and s.get("bidCount") is not None:
        buy += f" {s['bidCount']}b"
    seller = s.get("seller") or {}
    legacy = s.get("legacyItemId") or legacy_of(s.get("itemId"))
    loc = s.get("itemLocation") or {}
    return {
        "id": legacy, "title": s.get("title"), "price": _fmt(price, cur),
        "ship": "free" if ship == 0 else _fmt(ship) if ship is not None else "?",
        "cond": s.get("condition"), "buy": buy,
        "ends": _when(s.get("itemEndDate")) if "AUCTION" in opts else "",
        "seller": f"{seller.get('username') or '-'} {seller.get('feedbackPercentage') or '?'}% ({seller.get('feedbackScore', '?')})",
        "url": markets.item_url(market, legacy) if legacy else s.get("itemWebUrl"),
        # JSON-only extras
        "item_id": s.get("itemId"), "price_value": price, "currency": cur, "ship_value": ship,
        "total": round(price + ship, 2) if price is not None and ship is not None else None,
        "condition_id": s.get("conditionId"), "buying_options": opts, "end_time": s.get("itemEndDate"),
        "location": loc.get("country"), "image": (s.get("image") or {}).get("imageUrl"),
        "web_url": s.get("itemWebUrl"),
    }


ROW_FIELDS = ["id", "title", "price", "ship", "cond", "buy", "ends", "seller", "url"]


def search(params, loc):
    """-> (rows, total)."""
    r = ebay.get("/buy/browse/v1/item_summary/search", params, loc) or {}
    return [row(s, loc["market"]) for s in r.get("itemSummaries") or []], r.get("total", 0)


# ---- item lookup --------------------------------------------------------------------------------

def parse_ref(ref):
    """id | v1|..|.. | eBay URL -> ("rest", id) | ("legacy", id, variation or None)."""
    ref = ref.strip()
    if ref.startswith("v1|"):
        return ("rest", ref)
    if re.fullmatch(r"\d{9,15}", ref):
        return ("legacy", ref, None)
    if "ebay." in ref:
        u = urllib.parse.urlparse(ref if "://" in ref else "https://" + ref)
        q = urllib.parse.parse_qs(u.query)
        m = re.search(r"/itm/(?:[^/]+/)?(\d{9,15})", u.path)
        legacy = m.group(1) if m else (q.get("item") or [None])[0]
        if legacy:
            return ("legacy", legacy, (q.get("var") or [None])[0] or None)
    raise UsageError(f"not an eBay item id or URL: {ref!r} (expected 123456789012, v1|...|0 or an /itm/ link)")


def lookup(ref, loc):
    """-> (item, variations or None). Multi-variation listing: the cheapest variation + all of them."""
    kind = parse_ref(ref)
    if kind[0] == "rest":
        return ebay.get("/buy/browse/v1/item/" + urllib.parse.quote(kind[1], safe=""), None, loc), None
    params = {"legacy_item_id": kind[1]}
    if kind[2]:
        params["legacy_variation_id"] = kind[2]
    try:
        return ebay.get("/buy/browse/v1/item/get_item_by_legacy_id", params, loc), None
    except CliError as e:
        if 11006 not in http.error_ids(e):
            raise
    group = ebay.get("/buy/browse/v1/item/get_items_by_item_group", {"item_group_id": kind[1]}, loc) or {}
    items = group.get("items") or []
    if not items:
        raise UsageError(f"listing {kind[1]} has variations but eBay returned none")
    cheapest = min(items, key=lambda i: _money(i.get("price"))[0] or float("inf"))
    return cheapest, items


def _text(desc):
    t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", desc or "")
    t = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</h\d>", "\n", t)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    t = re.sub(r"[ \t\xa0]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n", t).strip()


def _aspects(it):
    return {a.get("name"): a.get("value") for a in it.get("localizedAspects") or []}


def card(it, loc, variations=None, full=False):
    """Item -> compact markdown."""
    price, cur = _money(it.get("price"))
    bid, bcur = _money(it.get("currentBidPrice"))
    legacy = it.get("legacyItemId") or ""
    L = [f"# {it.get('title')}", "",
         f"- id: {legacy} ({it.get('itemId')}) · {markets.item_url(loc['market'], legacy) if legacy else it.get('itemWebUrl')}"]
    opts = it.get("buyingOptions") or []
    if "AUCTION" in opts:
        L.append(f"- auction: current bid {_fmt(bid, bcur) or _fmt(price, cur)}, {it.get('bidCount', 0)} bids, "
                 f"ends {_when(it.get('itemEndDate'))}" + (" · reserve met" if it.get("reservePriceMet") else
                                                         " · reserve NOT met" if it.get("reservePriceMet") is False else ""))
        if "FIXED_PRICE" in opts:
            L.append(f"- buy it now: {_fmt(price, cur)}")
    else:
        L.append(f"- price: {_fmt(price, cur)} ({'+'.join(BUY_SHORT.get(o, o) for o in opts)})")
    dest = loc.get("ship_to") or "the default location"
    ships = it.get("shippingOptions") or []
    if ships:
        for o in ships[:3]:
            c, cc = _money(o.get("shippingCost"))
            est = " - ".join(x[:10] for x in (o.get("minEstimatedDeliveryDate"), o.get("maxEstimatedDeliveryDate")) if x)
            L.append(f"- shipping to {dest}: {'free' if c == 0 else _fmt(c, cc) or '?'}"
                     + "".join(f" · {x}" for x in (o.get("shippingServiceCode"), o.get("shippingCostType"), est and f"arrives {est}") if x)
                     + (f" · import charges {_fmt(*_money(o['importCharges']))}" if o.get("importCharges") else ""))
    else:
        L.append(f"- shipping to {dest}: no option returned (may not ship there; calculated rates need --zip)")
    rt = it.get("returnTerms") or {}
    if rt:
        per = rt.get("returnPeriod") or {}
        L.append("- returns: " + (f"accepted, {per.get('value')} {str(per.get('unit', '')).lower()}, "
                                  f"return shipping paid by {str(rt.get('returnShippingCostPayer', '?')).lower()}"
                                  if rt.get("returnsAccepted") else "not accepted"))
    cond = it.get("condition") or "?"
    L.append(f"- condition: {cond}" + (f" - {it['conditionDescription']}" if it.get("conditionDescription") else ""))
    s = it.get("seller") or {}
    L.append(f"- seller: {s.get('username') or '-'} {s.get('feedbackPercentage', '?')}% ({s.get('feedbackScore', '?')})"
             + (f", {s['sellerAccountType'].lower()}" if s.get("sellerAccountType") else ""))
    lc = it.get("itemLocation") or {}
    L.append("- location: " + ", ".join(x for x in (lc.get("city"), lc.get("postalCode"), lc.get("country")) if x))
    av = (it.get("estimatedAvailabilities") or [{}])[0]
    if av.get("estimatedAvailableQuantity") is not None or av.get("estimatedSoldQuantity") is not None:
        L.append(f"- available: {av.get('estimatedAvailableQuantity', '?')}, sold {av.get('estimatedSoldQuantity', 0)}")
    if variations:
        names = sorted({k for v in variations for k in _aspects(v)})
        differ = [n for n in names if len({_aspects(v).get(n) for v in variations}) > 1]
        L += ["", f"## Variations ({len(variations)}; card above = cheapest)", "",
              "| id | price | " + " | ".join(differ) + " |", "|---|---|" + "---|" * len(differ)]
        for v in variations:
            a = _aspects(v)
            L.append(f"| {v.get('itemId')} | {_fmt(*_money(v.get('price')))} | " + " | ".join(str(a.get(n, "")) for n in differ) + " |")
    asp = _aspects(it)
    if asp:
        L += ["", "## Item specifics", ""] + [f"- {k}: {v}" for k, v in asp.items()]
    desc = _text(it.get("description")) or it.get("shortDescription") or ""
    if desc:
        cut = not full and len(desc) > DESC_MAX
        L += ["", "## Description", "", desc[:DESC_MAX] if cut else desc]
        if cut:
            L.append(f"\n[cut at {DESC_MAX} of {len(desc)} chars - `ebay item {legacy or it.get('itemId')} --full` for all]")
    imgs = [(it.get("image") or {}).get("imageUrl")] + [i.get("imageUrl") for i in it.get("additionalImages") or []]
    imgs = [i for i in imgs if i]
    if imgs:
        L += ["", "## Images", ""] + [f"- {i}" for i in imgs]
    return "\n".join(L) + "\n"
