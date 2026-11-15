"""msg list: chat inbox, or one conversation (by listing or conversation id)."""
from ...api import account, query

FIELDS = ["conversation", "from", "ad", "last_by", "unread", "when", "last"]
THREAD = ["from", "time", "text"]
EPILOG = """examples:
  olx msg list                        # inbox: last_by=them -> the other side wrote last
  olx msg list --id 674669746         # whole conversation about that listing
  olx msg list --conversation abc123  # by the inbox's conversation column (no listing lookup)

Inbox: when = the site's own date text (time today, 'Ontem', dd/mm); unread = bold row.
Thread rows: from = me | the seller's name; time as the site shows it; -j adds label (the bubble's aria text).
No conversation yet with that listing -> no rows.
"""


def add_args(p):
    g = p.add_mutually_exclusive_group()
    g.add_argument("--id", metavar="ID|URL", help="conversation about this listing")
    g.add_argument("--conversation", metavar="CID", help="conversation id from the inbox")
    p.add_argument("--limit", type=int, default=25, help="inbox rows (default 25)")
    query.add_site_arg(p)


def run(ctx, args):
    s = query.site({"site": args.site}, ctx.cfg)
    if args.id or args.conversation:
        conv, rows = account.msg_thread(ctx.cfg, s, args.id, args.conversation)
        if not rows:
            ctx.note("no messages in this conversation yet")
        elif conv:
            ctx.note(f"conversation {conv}")
        ctx.write(rows, THREAD)
        return
    rows = account.msg_inbox(ctx.cfg, s, args.limit)
    if not rows:
        ctx.note("chat inbox is empty")
    ctx.write(rows, FIELDS)
