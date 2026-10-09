"""history: recent messages of one chat from the store, newest first."""
from ...api import messages, peers
from ...core.timeparse import parse_when

EPILOG = """examples:
  wa-cli history "Мама" -n 5
  wa-cli history 120363012345678901@g.us --since 1d --from "Иван"
  wa-cli history +351912345678 --offline
  wa-cli history "Мама" --ids 3EB0A1,3EB0B2 --offline --fields msg_id,my_reaction

CHAT: me | +phone | jid | exact or unique chat/contact name (ambiguous -> exit 2 with candidates).
Only what reached this device exists: messages since login + the phone's history sync. Text is cut
to text_limit (config, 200) - --full for whole messages. Media shows as [image] caption,
[document] name.pdf etc. (fields kind, file); save it: wa-cli download CHAT MSG_ID.
my_reaction (-j/--fields): own reaction emoji, null = none; only reactions that reached this device
(made from any of your devices after login, or in the history sync). --ids ignores -n/--since/--from.
"""


def add_args(p):
    p.add_argument("chat")
    p.add_argument("-n", "--limit", type=int, default=20)
    p.add_argument("--since", help="7d / 12h / 30m / 2w / YYYY-MM-DD / ISO")
    p.add_argument("--from", dest="sender", metavar="USER", help="only this sender (same forms as CHAT)")
    p.add_argument("--full", action="store_true", help="do not cut message text")
    p.add_argument("--offline", action="store_true", help="store only, no connect")
    p.add_argument("--ids", help="comma-separated msg ids: exactly these messages")


def run(ctx, args):
    store = ctx.synced_store()
    _, chat_jids, _ = peers.resolve(store, args.chat)
    sender_jids = peers.resolve(store, args.sender)[1] if args.sender else None
    text_limit = None if args.full else ctx.cfg["text_limit"]
    ids = [x.strip() for x in args.ids.split(",") if x.strip()] if args.ids else None
    rows = messages.history(store, chat_jids, args.limit, parse_when(args.since), sender_jids, text_limit, ids)
    ctx.write(rows, messages.MSG_FIELDS)
    if any(r["truncated"] for r in rows):
        ctx.note(f"text cut to {text_limit} chars - --full for whole messages")
    if not rows:
        ctx.note("no stored messages for this chat - only what reached this device since login exists")
