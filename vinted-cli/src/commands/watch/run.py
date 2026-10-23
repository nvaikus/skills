"""watch run: rerun saved searches, print only new listings and price drops."""
from ...api import notify, items, watch
from ...core.errors import Broken, CliError

FIELDS = ["watch", "change"] + items.ROW_FIELDS
EPILOG = """examples:
  vinted watch run                  # every saved search
  vinted watch run sofa gravel      # some of them
  vinted watch run --notify         # scheduled: one Telegram message when something is new / broke

change = new (never seen by this watch) | drop OLD>NEW (item price fell, same currency).
A re-listed or bumped item with the same id is not new (seen state is by id); one unseen for 60 days is forgotten.
Nothing new = empty stdout (TSV; -j prints []) and exit 0. A failing watch is noted on stderr, the others
still run, exit 1 at the end; Vinted blocking / changed page data stops the run, exit 3.
--notify: `claude-tg notify --topic <config notify_topic, default vinted>`; hits + failures only, a failure
repeats at most daily. Cron-ready: no prompts; state in ~/.claude/vinted/watch/.
"""


def add_args(p):
    p.add_argument("names", nargs="*", metavar="NAME", help="watches to run (default: all)")
    p.add_argument("--notify", action="store_true", help="send hits / failures to Telegram via claude-tg")
    p.add_argument("--topic", metavar="KEY", help="claude-tg notify topic key (default: config notify_topic)")


def run(ctx, args):
    rows, failed = watch.run(args.names, ctx.note)
    if rows or ctx.args.json:
        ctx.write(rows, FIELDS)
    else:
        ctx.note("nothing new")  # empty stdout: a scheduler can test for output
    if args.notify:
        due = notify.due_failures(failed)
        if rows or due:
            notify.send(notify.message(rows, due), args.topic or ctx.cfg.get("notify_topic") or "vinted", ctx.note)
    if failed:
        broken = [e for e in failed.values() if isinstance(e, Broken)]
        if broken:
            raise Broken(f"Vinted broke for {len(failed)} watch(es): {broken[0]}")
        raise CliError(f"{len(failed)} watch(es) failed: {', '.join(failed)}")
