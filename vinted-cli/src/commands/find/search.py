"""search: Vinted items -> one TSV row per listing."""
from ...api import items, query

FIELDS = items.ROW_FIELDS
EPILOG = """examples:
  vinted search "nike air max" --size 776 --max-price 40 --sort price
  vinted search levis 501 --condition new-tags,very-good --color blue
  vinted search --brand "the north face" --category 1206 --sort newest --limit 100
  vinted search "barbour" --site co.uk -j

Columns: id (use with `vinted show`); price = item price in cur (after a seller discount);
total = price + buyer-protection fee, shipping extra; brand, size, cond as Vinted shows them; url.
-j adds price_value, total_value, fee, was (pre-discount), promoted, favourites, seller_id, business, photo.
Results are cross-country (the site's whole shipping area); no location in rows.
Search is fuzzy: narrow with --category, --brand, --size, or --must WORDS (client-side title filter within
the --limit rows fetched, so raise --limit with it). 96 rows per page; Vinted serves at most 960 per query.
"""


def add_args(p):
    p.add_argument("query", nargs="*", metavar="QUERY", help="keywords")
    query.add_args(p)


def run(ctx, args):
    flags = query.flags_of(args)
    s = query.site(flags, ctx.cfg)
    query.check_limit(args.limit)
    q = " ".join(args.query).strip()
    must = query.must_words(flags)
    rows, total, promoted = items.search(s, query.params(q, flags, s, ctx.note), args.limit, must)
    if not rows:
        ctx.note(f"no items for {q!r} on vinted.{s}")
    elif must and len(rows) < args.limit:
        ctx.note(f"{len(rows)} rows left after --must (scanned up to {args.limit} of {total})")
    elif total > len(rows):
        ctx.note(f"{len(rows)} of {total} results" + (f" ({promoted} promoted)" if promoted else "")
                 + f"; narrow the query or raise --limit (max {query.MAX_LIMIT})")
    ctx.write(rows, FIELDS)
