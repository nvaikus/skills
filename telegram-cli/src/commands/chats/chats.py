"""chats: dialogs of the account."""
from ...api import peers

FIELDS = peers.PEER_FIELDS + ["unread", "last"]
TYPES = ("user", "bot", "group", "channel")
EPILOG = """examples:
  tg-cli chats                         # 50 most recent dialogs
  tg-cli chats саша --type user        # name/username substring, case-insensitive
  tg-cli chats --type channel -n 200 --fields id,name
  tg-cli chats -n 400 --fields id,name,muted,folders,unread_mentions

`id` is what history/search --chat/send accept. More keys via -j/--fields: muted (own or account default
for the type), archived, pinned, folders (explicitly listed only), members (null if not shipped), unread_mentions.
A filter scans every dialog (slower on big accounts).
"""


def add_args(p):
    p.add_argument("filter", nargs="?", help="substring of the name or username")
    p.add_argument("--type", action="append", choices=TYPES, help="repeatable")
    p.add_argument("-n", "--limit", type=int, default=50)


def run(ctx, args):
    rows = peers.dialogs(ctx.client(), args.filter, args.type, args.limit)
    ctx.write(rows, FIELDS)
    if len(rows) >= args.limit:
        ctx.note(f"showing the first {args.limit}; raise -n or narrow the filter for more")
