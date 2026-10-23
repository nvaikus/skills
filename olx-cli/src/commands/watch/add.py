"""watch add: save a search; the first check records the current listings as baseline."""
from ...api import query, watch
from ...core.errors import CliError

FIELDS = ["name", "site", "query", "flags", "limit", "seen"]
EPILOG = """examples:
  olx watch add "bicicleta gravel" --max-price 800 --region Lisboa
  olx watch add "sofa cama" --city Cascais --distance 20 --name sofa
  olx watch add --category bicicletas-de-estrada --max-price 600 --no-seed

Takes every `olx search` flag except --sort (runs always look at the newest first); --limit (default 50)
= how many newest listings each run looks at. Site, category, region and city are resolved to ids now
and stored with the watch. Right away it records the current matches as seen (`watch run` reports only
what appears later); --no-seed skips that request: the first `watch run` then records the baseline silently.
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
            ctx.note(f"watch {name}: {count} current listings recorded; `olx watch run` reports only newer ones")
        except CliError as e:
            ctx.note(f"watch {name} saved, but the first check failed ({e}); `watch run` will record the baseline")
    ctx.write([watch.describe(name, watch.searches()[name])], FIELDS)
