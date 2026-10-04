"""Search flags shared by `search` and `watch add`: argparse definitions -> Browse params + location."""
from ..core.errors import UsageError
from . import markets

CONDITIONS = {
    "new": "1000|1500|1750",                       # new, new other / open box, new with defects
    "used": "2990|3000|3010|4000|5000|6000",       # pre-owned excellent/fair, used, very good, good, acceptable
    "refurbished": "2000|2010|2020|2030|2500",     # certified, excellent, very good, good, seller refurbished
    "parts": "7000",                                # for parts or not working
}
BUYING = {"auction": "AUCTION", "fixed": "FIXED_PRICE", "best-offer": "BEST_OFFER"}
SORTS = {"best": None, "price": "price", "price-desc": "-price", "newest": "newlyListed", "ending": "endingSoonest"}
FLAGS = ("min_price", "max_price", "condition", "buying", "sort", "category", "market", "ship_to", "zip",
         "anywhere", "location")


def add_args(p, limit=20):
    p.add_argument("--min-price", type=float, metavar="N", help="in the market's currency")
    p.add_argument("--max-price", type=float, metavar="N", help="in the market's currency")
    p.add_argument("--condition", metavar="C[,C]", help=f"{' | '.join(CONDITIONS)} or raw condition ids (1000,3000)")
    p.add_argument("--buying", metavar="B[,B]", help=" | ".join(BUYING))
    p.add_argument("--sort", choices=list(SORTS), help="best (default) | price (item+shipping, low first) | "
                   "price-desc | newest | ending (auctions ending soonest)")
    p.add_argument("--category", metavar="ID", help="category id (find it with `ebay categories`)")
    p.add_argument("--location", metavar="CC", help="only items located in this country (itemLocationCountry)")
    p.add_argument("--anywhere", action="store_true", help="drop the ship-to filter (still prices shipping to it)")
    add_loc_args(p)
    if limit:
        p.add_argument("--limit", type=int, default=limit, metavar="N", help=f"rows (default {limit}, max 200)")


def add_loc_args(p):
    p.add_argument("--market", metavar="M", help="EBAY_DE, EBAY_GB, EBAY_US, ... (default: config)")
    p.add_argument("--ship-to", metavar="CC", help="country you ship to, e.g. PT (default: config)")
    p.add_argument("--zip", metavar="CODE", help="postal code for sharper shipping costs (default: config)")


def flags_of(args):
    """The search flags actually given (saved with a watch)."""
    return {k: getattr(args, k) for k in FLAGS if getattr(args, k, None) not in (None, False)}


def location(flags, cfg):
    market = markets.norm(flags.get("market") or cfg.get("market"))
    if not market:
        raise UsageError("no market: pass --market EBAY_DE (or similar) or set a default with "
                         "`ebay setup --market EBAY_DE --ship-to PT`")
    return {"market": market, "ship_to": markets.country(flags.get("ship_to") or cfg.get("ship_to")),
            "zip": flags.get("zip") or cfg.get("zip")}


def _multi(value, table, what):
    out = []
    for v in str(value).split(","):
        v = v.strip().lower()
        if v in table:
            out.append(table[v])
        elif what == "condition" and v.isdigit():
            out.append(v)
        else:
            raise UsageError(f"bad --{what} {v!r}: one of {', '.join(table)}")
    return "|".join(out)


def params(query, flags, loc, limit):
    """-> Browse item_summary/search query params."""
    if not query and not flags.get("category"):
        raise UsageError("give a QUERY or --category ID")
    if not 1 <= limit <= 200:
        raise UsageError("--limit must be 1..200")
    f = []
    lo, hi = flags.get("min_price"), flags.get("max_price")
    if lo is not None or hi is not None:
        rng = f"{lo:g}" if lo is not None else ""
        rng += f"..{hi:g}" if hi is not None else ""
        f += [f"price:[{rng}]", f"priceCurrency:{markets.currency(loc['market'])}"]
    if flags.get("condition"):
        f.append("conditionIds:{" + _multi(flags["condition"], CONDITIONS, "condition") + "}")
    if flags.get("buying"):
        f.append("buyingOptions:{" + _multi(flags["buying"], BUYING, "buying") + "}")
    if loc.get("ship_to") and not flags.get("anywhere"):
        f.append(f"deliveryCountry:{loc['ship_to']}")
    if flags.get("location"):
        f.append(f"itemLocationCountry:{markets.country(flags['location'])}")
    p = {"limit": limit}
    if query:
        p["q"] = query
    if f:
        p["filter"] = ",".join(f)
    if flags.get("category"):
        p["category_ids"] = str(flags["category"])
    if SORTS.get(flags.get("sort") or "best"):
        p["sort"] = SORTS[flags["sort"]]
    return p
