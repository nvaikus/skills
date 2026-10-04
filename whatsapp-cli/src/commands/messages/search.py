"""search: full-text search over the local store."""
from ...api import messages, peers
from ...core.timeparse import parse_when

EPILOG = """examples:
  wa-cli search "релиз 2.4"                          # every stored chat
  wa-cli search отпуск --chat "Команда QA" --from "Иван" --since 30d
  wa-cli search --chat +351912345678 --since 1d      # no words: latest messages of the chat

traps:
  local only (SQLite FTS5): WhatsApp has no server search, so only messages that reached this device.
  every word must match, each as a word prefix ("отпуск" finds "отпуска"); case/diacritics ignored.
  newest first.
"""


def add_args(p):
    p.add_argument("query", nargs="*", help="words; optional with --chat")
    p.add_argument("--chat", help="one chat: me | +phone | jid | chat/contact name")
    p.add_argument("--from", dest="sender", metavar="USER", help="sender filter (same forms)")
    p.add_argument("--since", help="7d / 12h / 2w / YYYY-MM-DD / ISO")
    p.add_argument("--until", help="same forms as --since")
    p.add_argument("-n", "--limit", type=int, default=50)
    p.add_argument("--full", action="store_true", help="do not cut message text")
    p.add_argument("--offline", action="store_true", help="store only, no connect")


def run(ctx, args):
    query = " ".join(args.query).strip()
    text_limit = None if args.full else ctx.cfg["text_limit"]
    store = ctx.synced_store()
    chat_jids = peers.resolve(store, args.chat)[1] if args.chat else None
    sender_jids = peers.resolve(store, args.sender)[1] if args.sender else None
    rows = messages.search(store, query, chat_jids, sender_jids, parse_when(args.since), parse_when(args.until),
                           args.limit, text_limit)
    ctx.write(rows, messages.MSG_FIELDS)
    if any(r["truncated"] for r in rows):
        ctx.note(f"text cut to {text_limit} chars - --full for whole messages")
    if len(rows) >= args.limit:
        ctx.note(f"showing {args.limit}; more may exist - raise -n or narrow with --since/--until")
