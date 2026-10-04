"""user-find: people, bots, groups, channels by name or username."""
from ...api import peers

FIELDS = peers.PEER_FIELDS + ["phone", "source"]
EPILOG = """examples:
  tg-cli user-find "Иван Петров"
  tg-cli user-find @durov
  tg-cli user-find +351912 --fields id,name,phone      # phone: your contacts only

source: contact (your contacts; the only rows with a phone) · username (exact @match) ·
mine (chats you are in) · global (Telegram-wide search by name/username; public entities only).
Queries shorter than 3 characters search contacts only.
"""


def add_args(p):
    p.add_argument("query", help="name, @username or phone fragment")
    p.add_argument("-n", "--limit", type=int, default=20)


def run(ctx, args):
    rows = peers.find(ctx.client(), args.query, args.limit)
    ctx.write(rows, FIELDS)
    if not rows:
        ctx.note(f"nothing found for {args.query!r}")
