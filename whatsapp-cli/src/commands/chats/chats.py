"""chats: chats in the local store."""
from ...api import peers

FIELDS = peers.PEER_FIELDS + ["unread", "last"]
TYPES = ("user", "group", "channel", "broadcast")
EPILOG = """examples:
  wa-cli chats                          # 50 most recent
  wa-cli chats саша --type user         # name/phone substring, case-insensitive
  wa-cli chats --type group -n 200 --fields jid,name --offline

`jid` (or a unique name, or +phone) is what history/search --chat/send accept.
Chats appear once a message or the history sync has mentioned them.
Channels the account does not follow (read via channel-fetch) are hidden; --all lists them too
(-j: following false). Their posts stay searchable either way.
"""


def add_args(p):
    p.add_argument("filter", nargs="?", help="substring of the name, phone or jid")
    p.add_argument("--type", action="append", choices=TYPES, help="repeatable")
    p.add_argument("-n", "--limit", type=int, default=50)
    p.add_argument("--all", action="store_true", help="include channels the account does not follow")
    p.add_argument("--offline", action="store_true", help="store only, no connect")


def run(ctx, args):
    rows = peers.chat_rows(ctx.synced_store(), args.filter, args.type, args.limit, unfollowed=args.all)
    ctx.write(rows, FIELDS)
    if len(rows) >= args.limit:
        ctx.note(f"showing the first {args.limit}; raise -n or narrow the filter for more")
