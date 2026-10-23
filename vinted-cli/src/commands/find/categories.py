"""categories: ids + names for --category."""
from ...api import categories, query, vinted

FIELDS = ["id", "name", "path", "level"]
EPILOG = """examples:
  vinted categories                     # top level (Women, Men, Kids, Home, ...)
  vinted categories --under 5           # children of a category
  vinted categories --grep sneakers     # names/paths/slugs containing the words, all levels

Names are in the site's language (vinted.pt = Portuguese; --grep matches slugs too, mostly English).
Tree from a catalog page, cached a week (~/.claude/vinted/cache/); --refresh reloads.
search --category takes the id, an exact name, a slug or a path tail ("Homem > Calçado").
"""


def add_args(p):
    p.add_argument("--under", metavar="ID|NAME", help="list the children of this category")
    p.add_argument("--grep", metavar="WORDS", help="names/paths/slugs containing every word")
    p.add_argument("--refresh", action="store_true", help="reload the cached category tree")
    query.add_site_arg(p)


def run(ctx, args):
    s = vinted.site(args.site or ctx.cfg.get("site"))
    rows = categories.browse(categories.tree(s, args.refresh), args.under, args.grep)
    if not rows:
        ctx.note("no categories")
    ctx.write(rows, FIELDS)
