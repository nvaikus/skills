"""show: one item as a compact markdown card."""
from ...api import items, query

EPILOG = """examples:
  vinted show 7123456789
  vinted show "https://www.vinted.fr/items/7123456789-veste-nike"
  vinted show 7123456789 --full -j

Shows: price · total with buyer protection (fee), shipping from, brand / size / condition / color,
category, uploaded · state (available / reserved / hidden), seller (private/business, rating /5, reviews),
photo URLs (4 unless --full), description (cut at 1500 chars unless --full).
A URL's host picks the site. Sold-and-removed item -> exit 2. Vinted shows no item location.
"""


def add_args(p):
    p.add_argument("ref", metavar="ID|URL", help="numeric item id or a Vinted item URL")
    p.add_argument("--full", action="store_true", help="every photo and the whole description")
    query.add_site_arg(p)


def run(ctx, args):
    fl, html, s, item_id = items.lookup(args.ref, query.site(query.flags_of(args), ctx.cfg))
    d = items.details(fl, html, s, item_id)
    ctx.text(items.card(d, args.full), d)
