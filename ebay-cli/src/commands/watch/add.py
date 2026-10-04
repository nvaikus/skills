"""watch add: save a search; the first check records the current items as baseline."""
from ...api import query, watch
from ...core.errors import CliError

FIELDS = ["name", "query", "flags", "limit", "seen"]
EPILOG = """examples:
  ebay watch add "thinkpad x1 carbon gen 9" --max-price 450 --condition used,refurbished
  ebay watch add "lego 10294" --buying fixed --name titanic
  ebay watch add "fuji x100v" --market EBAY_GB --no-seed

Takes every `ebay search` flag; --limit (default 50) = how many newest listings each run looks at.
Market / ship-to not given are taken from the config at run time (a later default change applies).
Right away it records the current matches as seen (so `watch run` reports only what appears later);
--no-seed skips that call: the first `watch run` then records the baseline silently.
"""


def add_args(p):
    p.add_argument("query", nargs="*", metavar="QUERY")
    p.add_argument("--name", metavar="NAME", help="short name (default: from the query)")
    p.add_argument("--no-seed", action="store_true", help="do not record the current items now")
    query.add_args(p, limit=watch.DEFAULT_LIMIT)


def run(ctx, args):
    q = " ".join(args.query).strip()
    flags = query.flags_of(args)
    loc = query.location(flags, ctx.cfg)
    query.params(q, flags, loc, args.limit)  # validate before saving
    name = watch.add(args.name, q, flags, args.limit)
    if not args.no_seed:
        try:
            _, _, count = watch.check(name, watch.searches()[name], ctx.cfg)
            ctx.note(f"watch {name}: {count} current items recorded; `ebay watch run` reports only newer ones")
        except CliError as e:
            ctx.note(f"watch {name} saved, but the first check failed ({e}); `watch run` will record the baseline")
    ctx.write([watch.describe(name, watch.searches()[name])], FIELDS)
