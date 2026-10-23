"""watch add: save a search; the first check records the current listings as baseline."""
from ...api import query, watch
from ...core.errors import CliError

FIELDS = ["name", "site", "query", "flags", "limit", "seen"]
EPILOG = """examples:
  vinted watch add "nike air max 90" --size 776 --max-price 50
  vinted watch add --brand patagonia --category 1206 --name patagonia
  vinted watch add "barbour" --site co.uk --condition very-good --no-seed

Takes every `vinted search` flag except --sort (runs always look at the newest first); --limit (default 50)
= how many newest items each run looks at. Site, category and brand names are resolved to ids now and
stored with the watch. Right away it records the current matches as seen (`watch run` reports only what
appears later); --no-seed skips that request: the first `watch run` then records the baseline silently.
"""


def add_args(p):
    p.add_argument("query", nargs="*", metavar="QUERY")
    p.add_argument("--name", metavar="NAME", help="short name (default: from the query)")
    p.add_argument("--no-seed", action="store_true", help="do not record the current listings now")
    query.add_args(p, limit=watch.DEFAULT_LIMIT)


def run(ctx, args):
    q = " ".join(args.query).strip()
    flags = query.flags_of(args)
    flags.pop("sort", None)
    s = query.site(flags, ctx.cfg)
    query.check_limit(args.limit)
    params = query.params(q, flags, s, ctx.note)
    name = watch.add(args.name, q, flags, params, s, args.limit)
    if not args.no_seed:
        try:
            _, _, count = watch.check(name, watch.searches()[name])
            ctx.note(f"watch {name}: {count} current listings recorded; `vinted watch run` reports only newer ones")
        except CliError as e:
            ctx.note(f"watch {name} saved, but the first check failed ({e}); `watch run` will record the baseline")
    ctx.write([watch.describe(name, watch.searches()[name])], FIELDS)
