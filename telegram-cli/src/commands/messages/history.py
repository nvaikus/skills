"""history: recent messages of one chat, newest first."""
from ...api import messages, peers
from ...core.errors import UsageError
from ...core.timeparse import parse_when

EPILOG = """examples:
  tg-cli history @durov -n 5
  tg-cli history "Команда QA" --since 1d --from @ivan
  tg-cli history me -n 3                 # Saved Messages
  tg-cli history @ivan --ids 120,131 --fields msg_id,my_reaction   # exactly these messages

CHAT: me | id | @username | t.me link | exact or unique dialog/contact name (ambiguous -> exit 2
with the candidates). Text is cut to text_limit (config, 200) - --full for whole messages.
More keys via -j/--fields: out, reply_to_msg_id, reply_to_me (one extra lookup for older targets), mentions_me,
my_reaction (this account's own reaction emoji, '[custom]' for a custom emoji; null = none).
--ids ignores -n/--since/--from; ids missing from the chat are skipped silently.
"""


def add_args(p):
    p.add_argument("chat")
    p.add_argument("-n", "--limit", type=int, default=20)
    p.add_argument("--since", help="7d / 12h / 30m / 2w / YYYY-MM-DD / ISO")
    p.add_argument("--from", dest="sender", metavar="USER", help="only this sender (same forms as CHAT)")
    p.add_argument("--full", action="store_true", help="do not cut message text")
    p.add_argument("--ids", help="comma-separated msg ids: fetch exactly these (one request)")


def run(ctx, args):
    client = ctx.client()
    chat = peers.resolve(client, args.chat)
    sender = peers.resolve(client, args.sender) if args.sender else None
    text_limit = None if args.full else ctx.cfg["text_limit"]
    try:
        ids = [int(x) for x in args.ids.split(",") if x.strip()] if args.ids else None
    except ValueError:
        raise UsageError(f"--ids: comma-separated integers expected, got {args.ids!r}")
    rows = messages.history(client, chat, args.limit, parse_when(args.since), sender, text_limit, ids)
    ctx.write(rows, messages.MSG_FIELDS)
    if any(r["truncated"] for r in rows):
        ctx.note(f"text cut to {text_limit} chars - --full for whole messages")
