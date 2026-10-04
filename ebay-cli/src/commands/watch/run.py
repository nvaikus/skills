"""watch run: rerun saved searches, print only new listings and price drops."""
from ...api import browse, watch
from ...core.errors import CliError

FIELDS = ["watch", "change"] + browse.ROW_FIELDS
EPILOG = """examples:
  ebay watch run                 # every saved search
  ebay watch run titanic x1      # some of them
  ebay watch run -j              # for scripts / schedulers

change = new (never seen by this watch) | drop OLD>NEW (fixed price fell; auctions are not compared).
Nothing new = empty stdout (TSV; -j prints []) and exit 0. A failing watch is noted on stderr, the others still run, exit 1 at the end.
Each watch costs one API call; eBay allows ~5000 per day per app.
Cron-ready: no prompts; state in ~/.claude/ebay/watch/. Scheduling is up to the caller.
"""


def add_args(p):
    p.add_argument("names", nargs="*", metavar="NAME", help="watches to run (default: all)")


def run(ctx, args):
    rows, failed = watch.run(args.names, ctx.cfg, ctx.note)
    if rows or ctx.args.json:
        ctx.write(rows, FIELDS)
    else:
        ctx.note("nothing new")  # empty stdout: a scheduler can test for output
    if failed:
        raise CliError(f"{len(failed)} watch(es) failed: {', '.join(failed)}")
