"""item: one listing as a compact markdown card."""
from ...api import browse, query

EPILOG = """examples:
  ebay item 256123456789
  ebay item "https://www.ebay.de/itm/256123456789?var=555"
  ebay item "v1|256123456789|0" --ship-to DE
  ebay item 256123456789 --full -j

Shows: price (auction: bid, bids, end, reserve), shipping to --ship-to with delivery estimate, returns,
condition + seller notes, seller, location, availability, item specifics, description (cut at 1500
chars unless --full), image URLs. A listing with variations (sizes, colours): card of the cheapest +
a table of all variations; `ebay item 'v1|..|..'` for one of them.
"""


def add_args(p):
    p.add_argument("ref", metavar="ID|URL", help="listing id, RESTful v1|..|.. id, or an eBay /itm/ URL")
    p.add_argument("--full", action="store_true", help="the whole description")
    query.add_loc_args(p)


def run(ctx, args):
    loc = query.location(query.flags_of(args), ctx.cfg)
    it, variations = browse.lookup(args.ref, loc)
    ctx.text(browse.card(it, loc, variations, args.full),
             {"item_id": it.get("itemId"), "id": it.get("legacyItemId"), "item": it, "variations": variations})
