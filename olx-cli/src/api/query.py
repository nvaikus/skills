"""Search flags shared by `search` and `watch add`: argparse definitions -> OLX offers params."""
from ..core.errors import UsageError
from . import categories, olx

SORTS = {"best": None, "price": "filter_float_price:asc", "price-desc": "filter_float_price:desc",
         "newest": "created_at:desc"}
CONDITIONS = ("new", "used")
SELLERS = ("private", "business")
FLAGS = ("min_price", "max_price", "category", "region", "city", "distance", "condition", "seller", "sort", "site",
         "must")


def add_args(p, limit=20):
    p.add_argument("--min-price", type=float, metavar="N", help="in the site's currency")
    p.add_argument("--max-price", type=float, metavar="N", help="in the site's currency")
    p.add_argument("--category", metavar="ID|NAME", help="id or name/path (find with `olx categories QUERY`)")
    p.add_argument("--region", metavar="ID|NAME", help="region (district), e.g. Lisboa; ids: `olx places --regions`")
    p.add_argument("--city", metavar="ID|NAME", help="city/parish, e.g. Ericeira; ids: `olx places NAME`")
    p.add_argument("--distance", type=int, metavar="KM", help="radius around --city (km)")
    p.add_argument("--condition", choices=CONDITIONS, help="item state param (not every category has it)")
    p.add_argument("--seller", choices=SELLERS, help="private persons or businesses only")
    p.add_argument("--must", metavar="W[,W]", help="keep only titles containing every word (prefix, accents ignored);"
                   " OLX's own query is fuzzy")
    p.add_argument("--sort", choices=list(SORTS), help="best (default, relevance) | price (low first) | "
                   "price-desc | newest (last refreshed first)")
    add_site_arg(p)
    if limit:
        p.add_argument("--limit", type=int, default=limit, metavar="N", help=f"rows (default {limit}, max 200)")


def add_site_arg(p):
    p.add_argument("--site", metavar="CC", help=f"OLX country: {' '.join(olx.SITES)} (default: config, pt)")


def flags_of(args):
    """The search flags actually given (saved with a watch)."""
    return {k: getattr(args, k) for k in FLAGS if getattr(args, k, None) not in (None, False)}


def site(flags, cfg):
    return olx.site(flags.get("site") or cfg.get("site"))


def _city(s, value):
    v = str(value).strip()
    if v.isdigit():
        return int(v), None
    hits = olx.autocomplete(s, v)
    if not hits:
        raise UsageError(f"no city {value!r} on {olx.SITES[s]}: try `olx places {value}`")
    c = hits[0]["city"]
    return c["id"], f"{c['name']}, {(hits[0].get('region') or {}).get('name') or ''}".strip(", ")


def _region(s, value):
    v = str(value).strip()
    if v.isdigit():
        return int(v), None
    f = categories.fold(v)
    hits = [r for r in olx.regions(s) if f in (categories.fold(r.get("name")), r.get("normalized_name"))]
    if not hits:
        raise UsageError(f"no region {value!r} on {olx.SITES[s]}: list them with `olx places --regions`")
    return hits[0]["id"], hits[0]["name"]


def params(query, flags, s, note=None):
    """-> OLX /offers params (without offset/limit). Names (category/region/city) resolve to ids here."""
    if not query and not flags.get("category"):
        raise UsageError("give a QUERY or --category")
    p = {}
    if query:
        p["query"] = query
    lo, hi = flags.get("min_price"), flags.get("max_price")
    if lo is not None and hi is not None and lo > hi:
        raise UsageError("--min-price is above --max-price")
    if lo is not None:
        p["filter_float_price:from"] = f"{lo:g}"
    if hi is not None:
        p["filter_float_price:to"] = f"{hi:g}"
    if flags.get("category"):
        c = str(flags["category"])
        p["category_id"] = int(c) if c.isdigit() else categories.resolve(categories.tree(s), c)
    if flags.get("city"):
        p["city_id"], shown = _city(s, flags["city"])
        if shown and note:
            note(f"city {flags['city']!r} = {shown} (id {p['city_id']})")
    if flags.get("region") and not flags.get("city"):
        p["region_id"], _ = _region(s, flags["region"])
    if flags.get("distance") is not None:
        if not flags.get("city"):
            raise UsageError("--distance needs --city")
        p["distance"] = int(flags["distance"])
    if flags.get("condition"):
        p["filter_enum_state[0]"] = flags["condition"]
    if flags.get("seller"):
        p["owner_type"] = flags["seller"]
    if SORTS.get(flags.get("sort") or "best"):
        p["sort_by"] = SORTS[flags["sort"]]
    return p


def check_limit(limit):
    if not 1 <= limit <= 200:
        raise UsageError("--limit must be 1..200")


def must_words(flags):
    """--must 'gravel,52' -> folded words, or None."""
    if not flags.get("must"):
        return None
    words = [categories.fold(w).strip() for w in str(flags["must"]).replace(" ", ",").split(",")]
    return [w for w in words if w] or None
