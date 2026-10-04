"""search: Browse item_summary/search -> one TSV row per listing."""
from ...api import browse, query

FIELDS = browse.ROW_FIELDS
EPILOG = """examples:
  ebay search "thinkpad x1 carbon" --max-price 400 --condition used,refurbished --sort price
  ebay search "lego 10294" --buying auction --sort ending
  ebay search "nikon z 50mm" --market EBAY_GB --ship-to PT -j
  ebay search --category 111422 "x1 carbon" --limit 50

Defaults: --market / --ship-to from `ebay setup`. Only listings that ship to --ship-to are returned
(--anywhere drops that filter); shipping is priced for that country.
Columns: id = listing id (use with `ebay item`); price = current bid for auctions; ship = cheapest
shipping to you (free | ? = no cost returned); buy = fixed / auction Nb (bids) / offer; ends = auctions only (UTC);
seller = name feedback% (score); url = short link. -j adds item_id, total, currency, end_time, image, location.
--sort price = item + shipping, low first. --min/--max-price are in the market's currency.
Results: at most 200 per call; the '# N of TOTAL' note says when there is more.
"""


def add_args(p):
    p.add_argument("query", nargs="*", metavar="QUERY", help="keywords (AND); (a,b) = OR; -word excludes")
    query.add_args(p)


def run(ctx, args):
    flags = query.flags_of(args)
    loc = query.location(flags, ctx.cfg)
    q = " ".join(args.query).strip()
    rows, total = browse.search(query.params(q, flags, loc, args.limit), loc)
    if not rows:
        ctx.note(f"no listings for {q!r} on {loc['market']}" + (f" shipping to {loc['ship_to']}" if loc["ship_to"] else ""))
    elif total > len(rows):
        ctx.note(f"{len(rows)} of {total} results; narrow the query or raise --limit (max 200)")
    ctx.write(rows, FIELDS)
