"""search: OLX offers -> one TSV row per listing."""
from ...api import offers, query

FIELDS = offers.ROW_FIELDS
EPILOG = """examples:
  olx search "bicicleta btt" --max-price 300 --sort price
  olx search iphone 13 --city Lisboa --distance 30 --condition used --seller private
  olx search --category bicicletas --region Porto --sort newest --limit 50
  olx search "rower" --site pl -j

Columns: id = listing id (use with `olx show`); price = number in cur, "neg" = negotiable, swap = exchange
only, free, ask = no price given, - = category without price; was = old price OLX shows after a cut;
date = last refresh (sellers refresh to bump; created is in -j); url = full listing link.
-j adds price_value, price_kind, region, created, refreshed, category_id, condition, business, seller, photos, courier.
Search is fuzzy (matches descriptions, other categories, word forms): narrow with --category, --min-price,
--must WORDS (client-side title filter; it filters within the --limit rows fetched, so raise --limit with it).
Promoted top ads are dropped (they ignore --sort). Max 200 rows; OLX serves only the first ~1000 of any query.
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
    rows, total, promoted = offers.search(s, query.params(q, flags, s, ctx.note), args.limit, must)
    if not rows:
        ctx.note(f"no listings for {q!r} on olx.{s}")
    elif must and len(rows) < args.limit:
        ctx.note(f"{len(rows)} rows left after --must (scanned up to {args.limit} newest-by-sort of {total})")
    elif total > len(rows):
        ctx.note(f"{len(rows)} of {total} results" + (f" ({promoted} promoted skipped)" if promoted else "")
                 + "; narrow the query or raise --limit (max 200)")
    ctx.write(rows, FIELDS)
