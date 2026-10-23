"""Search flags shared by `search` and `watch add`: argparse definitions -> Vinted /catalog params."""
from ..core.errors import UsageError
from . import categories, filters, vinted

SORTS = {"best": None, "newest": "newest_first", "price": "price_low_to_high", "price-desc": "price_high_to_low"}
FLAGS = ("min_price", "max_price", "category", "brand", "size", "condition", "color", "currency", "sort", "site",
         "must")
MAX_LIMIT = vinted.PAGE * vinted.MAX_PAGES


def add_args(p, limit=20):
    p.add_argument("--min-price", type=float, metavar="N", help="item price, without the buyer-protection fee")
    p.add_argument("--max-price", type=float, metavar="N", help="item price, without the buyer-protection fee")
    p.add_argument("--category", metavar="ID|NAME[,..]", help="catalog id(s) or name/slug (`vinted categories --grep X`)")
    p.add_argument("--brand", metavar="ID|NAME[,..]", help="brand id(s) or name(s) (`vinted brands X`)")
    p.add_argument("--size", metavar="ID[,..]", help="size id(s) (`vinted sizes --category ID`)")
    p.add_argument("--condition", metavar="C[,..]", help=f"{', '.join(filters.CONDITIONS)} or ids (`vinted conditions`)")
    p.add_argument("--color", metavar="C[,..]", help="black, white, navy ... or ids (`vinted colors`)")
    p.add_argument("--currency", metavar="CUR", help="price filter currency, e.g. EUR (default: the site's)")
    p.add_argument("--must", metavar="W[,W]", help="keep only titles containing every word (prefix, accents ignored);"
                   " Vinted's own query is fuzzy")
    p.add_argument("--sort", choices=list(SORTS), help="best (default, relevance) | newest | price (low first) | "
                   "price-desc")
    add_site_arg(p)
    if limit:
        p.add_argument("--limit", type=int, default=limit, metavar="N", help=f"rows (default {limit}, max {MAX_LIMIT})")


def add_site_arg(p):
    p.add_argument("--site", metavar="TLD", help=f"Vinted domain: {' '.join(vinted.SITES)} (default: config, pt)")


def flags_of(args):
    """The search flags actually given (saved with a watch)."""
    return {k: getattr(args, k) for k in FLAGS if getattr(args, k, None) not in (None, False)}


def site(flags, cfg):
    return vinted.site(flags.get("site") or cfg.get("site"))


def _categories(s, value):
    vals = [v.strip() for v in str(value).split(",") if v.strip()]
    if all(v.isdigit() for v in vals):
        return [int(v) for v in vals]
    t = categories.tree(s)
    return [categories.resolve(t, v) for v in vals]


def params(query, flags, s, note=None):
    """-> Vinted /catalog params (without page). Names (category/brand/condition/color) resolve to ids here."""
    if not query and not (flags.get("category") or flags.get("brand")):
        raise UsageError("give a QUERY, --category or --brand")
    p = {}
    if query:
        p["search_text"] = query
    lo, hi = flags.get("min_price"), flags.get("max_price")
    if lo is not None and hi is not None and lo > hi:
        raise UsageError("--min-price is above --max-price")
    if lo is not None:
        p["price_from"] = f"{lo:g}"
    if hi is not None:
        p["price_to"] = f"{hi:g}"
    if flags.get("currency"):
        p["currency"] = str(flags["currency"]).upper()
    if flags.get("category"):
        p["catalog[]"] = _categories(s, flags["category"])
    if flags.get("brand"):
        p["brand_ids[]"] = filters.brand_ids(s, flags["brand"], note)
    if flags.get("size"):
        p["size_ids[]"] = filters.ids(flags["size"], {}, "size", "sizes --category ID")
    if flags.get("condition"):
        p["status_ids[]"] = filters.ids(flags["condition"], filters.CONDITIONS, "condition", "conditions")
    if flags.get("color"):
        p["color_ids[]"] = filters.ids(flags["color"], filters.COLORS, "color", "colors")
    if SORTS.get(flags.get("sort") or "best"):
        p["order"] = SORTS[flags["sort"]]
    return p


def check_limit(limit):
    if not 1 <= limit <= MAX_LIMIT:
        raise UsageError(f"--limit must be 1..{MAX_LIMIT}")


def must_words(flags):
    """--must 'gravel,52' -> folded words, or None."""
    if not flags.get("must"):
        return None
    words = [categories.fold(w).strip() for w in str(flags["must"]).replace(" ", ",").split(",")]
    return [w for w in words if w] or None
