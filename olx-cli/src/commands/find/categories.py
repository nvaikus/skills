"""categories: ids + names for --category."""
from ...api import categories, olx, query

FIELDS = ["id", "count", "path"]
EPILOG = """examples:
  olx categories bicicleta              # categories holding matches, most first (count = listings)
  olx categories                        # top level
  olx categories --under 9              # children of a category
  olx categories --grep telemoveis      # names/paths containing a word, all levels

Names come from the site's home page, cached a week (~/.claude/olx/cache/); --refresh reloads.
search --category takes the id, an exact name or a path tail ("bicicletas-de-cidade").
"""


def add_args(p):
    p.add_argument("query", nargs="*", metavar="QUERY", help="search words: categories with matches")
    p.add_argument("--under", metavar="ID|NAME", help="list the children of this category")
    p.add_argument("--grep", metavar="WORD", help="names/paths containing WORD")
    p.add_argument("--refresh", action="store_true", help="reload the cached category tree")
    p.add_argument("--limit", type=int, default=25, metavar="N", help="rows for QUERY (default 25)")
    query.add_site_arg(p)


def run(ctx, args):
    s = olx.site(args.site or ctx.cfg.get("site"))
    t = categories.tree(s, args.refresh)
    q = " ".join(args.query).strip()
    rows = categories.for_query(s, q, t)[:args.limit] if q else categories.browse(t, args.under, args.grep)
    if not rows:
        ctx.note("no categories")
    ctx.write(rows, FIELDS)
