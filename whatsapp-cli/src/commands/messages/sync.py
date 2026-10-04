"""sync: pull what arrived since the last run into the store, report counts."""
from ...api import peers, sync

FIELDS = ["account", "new", "chats", "contacts", "messages", "synced"]
EPILOG = """examples:
  wa-cli sync
  wa-cli sync --wait 60          # wait longer for a big offline backlog

Every reading command already syncs first; use this to refresh the store before several --offline
reads, or on a schedule. Not a daemon: it drains the queue and exits (`--follow` is planned).
"""


def add_args(p):
    p.add_argument("--wait", type=int, metavar="S", help="max seconds to drain (default: config sync_wait)")


def run(ctx, args):
    s = ctx.session(drain=False)
    stats = sync.drain(s, ctx.store(), maximum=args.wait or ctx.cfg["sync_wait"], force_refresh=True)
    st = ctx.store()
    row = {"account": ctx.account, "new": stats.get("messages", 0), **st.counts(),
           "synced": peers.iso_ts(int(st.get_meta("synced", 0) or 0))}
    ctx.write([row], FIELDS, receipt=True)
