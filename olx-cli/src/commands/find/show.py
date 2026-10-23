"""show: one listing as a compact markdown card."""
from ...api import offers, query

EPILOG = """examples:
  olx show 674668916
  olx show "https://www.olx.pt/d/anuncio/bicicleta-btwin-riverside-500-IDJEQcI.html"
  olx show 123456789 --site pl --full -j

Shows: price (negotiable / was), place, posted · refreshed · valid-to · status, seller (private/business,
on OLX since, last seen), contact options (chat, phone, courier = OLX delivery), photo count + first photo,
params (condition, size...), description (cut at 1500 chars unless --full).
A URL is resolved to the id from the listing page (one extra request); its host picks the site.
Removed/expired listing -> exit 2. All photos as files: `olx photos ID`.
"""


def add_args(p):
    p.add_argument("ref", metavar="ID|URL", help="numeric listing id or an OLX listing URL")
    p.add_argument("--full", action="store_true", help="the whole description")
    query.add_site_arg(p)


def run(ctx, args):
    o, s = offers.lookup(args.ref, query.site(query.flags_of(args), ctx.cfg))
    ctx.text(offers.card(o, args.full), {"id": o.get("id"), "site": s, "offer": o})
