"""categories: Taxonomy category suggestions."""
from ...api import query, taxonomy
from ...core.errors import UsageError

FIELDS = ["id", "name", "path"]
EPILOG = """examples:
  ebay categories "mechanical keyboard"
  ebay categories "road bike" --market EBAY_GB

Ids differ per market's category tree: look them up with the --market you will search.
Next: ebay search --category ID "QUERY".
"""


def add_args(p):
    p.add_argument("query", nargs="+", metavar="QUERY")
    p.add_argument("--market", metavar="M", help="category tree of this market (default: config)")


def run(ctx, args):
    q = " ".join(args.query).strip()
    if not q:
        raise UsageError("give a QUERY")
    loc = query.location({"market": args.market}, ctx.cfg)
    rows = taxonomy.suggest(q, loc)
    if not rows:
        ctx.note(f"no category suggestions for {q!r} on {loc['market']}")
    ctx.write(rows, FIELDS)
