"""sizes: size ids of a category for --size."""
from ...api import categories, filters, query, vinted

FIELDS = ["id", "group", "name"]
EPILOG = """examples:
  vinted sizes --category 1231               # men's shoes
  vinted sizes --category 4 --grep 38

Size ids depend on the category family (clothing, shoes, kids...). First call per site + category probes
~6 catalog pages (a minute); then cached a month (--refresh reloads). Use the most specific category you
search in: a parent may list several size systems.
"""


def add_args(p):
    p.add_argument("--category", required=True, metavar="ID|NAME", help="category (`vinted categories`)")
    p.add_argument("--grep", metavar="TEXT", help="names/groups containing TEXT")
    p.add_argument("--refresh", action="store_true", help="probe again")
    query.add_site_arg(p)


def run(ctx, args):
    s = vinted.site(args.site or ctx.cfg.get("site"))
    cat = int(args.category) if str(args.category).isdigit() else categories.resolve(categories.tree(s),
                                                                                       args.category)
    rows = filters.sizes(s, cat, args.refresh)
    if args.grep:
        g = categories.fold(args.grep)
        rows = [r for r in rows if g in categories.fold(f"{r['group']} {r['name']}")]
    if not rows:
        ctx.note(f"no sizes for category {cat}")
    ctx.write(rows, FIELDS)
