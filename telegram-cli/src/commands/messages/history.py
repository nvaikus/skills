"""history: recent messages of one chat, newest first."""
from ...api import messages, peers
from ...core.timeparse import parse_when

EPILOG = """examples:
  tg-cli history @durov -n 5
  tg-cli history "Команда QA" --since 1d --from @ivan
  tg-cli history me -n 3                 # Saved Messages

CHAT: me | id | @username | t.me link | exact or unique dialog/contact name (ambiguous -> exit 2
with the candidates). Text is cut to text_limit (config, 200) - --full for whole messages.
More keys via -j/--fields: out, reply_to_msg_id, reply_to_me (one extra lookup for older targets), mentions_me.
"""


def add_args(p):
    p.add_argument("chat")
    p.add_argument("-n", "--limit", type=int, default=20)
    p.add_argument("--since", help="7d / 12h / 30m / 2w / YYYY-MM-DD / ISO")
    p.add_argument("--from", dest="sender", metavar="USER", help="only this sender (same forms as CHAT)")
    p.add_argument("--full", action="store_true", help="do not cut message text")


def run(ctx, args):
    client = ctx.client()
    chat = peers.resolve(client, args.chat)
    sender = peers.resolve(client, args.sender) if args.sender else None
    text_limit = None if args.full else ctx.cfg["text_limit"]
    rows = messages.history(client, chat, args.limit, parse_when(args.since), sender, text_limit)
    ctx.write(rows, messages.MSG_FIELDS)
    if any(r["truncated"] for r in rows):
        ctx.note(f"text cut to {text_limit} chars - --full for whole messages")
