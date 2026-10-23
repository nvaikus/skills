"""brands: brand ids for --brand."""
from ...api import filters, query, vinted

FIELDS = ["id", "name", "items", "slug"]
EPILOG = """examples:
  vinted brands nike
  vinted brands "north face" --limit 5

items = listings of that brand on the site. search --brand takes ids or names (a name = exact match, else
the top hit, noted on stderr). Uses Vinted's JSON API with the anonymous cookie of the home page
(cached an hour in ~/.claude/vinted/session-<site>.json).
"""


def add_args(p):
    p.add_argument("keyword", nargs="+", metavar="KEYWORD")
    p.add_argument("--limit", type=int, default=20, metavar="N", help="rows (default 20)")
    query.add_site_arg(p)


def run(ctx, args):
    s = vinted.site(args.site or ctx.cfg.get("site"))
    rows = filters.brand_rows(s, " ".join(args.keyword))[:args.limit]
    if not rows:
        ctx.note("no brands")
    ctx.write(rows, FIELDS)
