"""search: messages across all dialogs, inside one chat, or across all public channels."""
from ...api import messages, peers
from ...core.errors import UsageError
from ...core.timeparse import parse_when

EPILOG = """examples:
  tg-cli search "релиз 2.4"                        # every chat, group and channel you are in
  tg-cli search отпуск --chat "Команда QA" --from @ivan --since 30d
  tg-cli search --chat @somechannel "api"          # public chat you have not joined
  tg-cli search --public "claude code"             # all public channels: daily free quota
  tg-cli search --public "#ai"                     # hashtag: free

traps:
  Telegram matches whole words, not substrings; results are newest first.
  --from needs --chat (global search has no sender filter).
  --public spends one free daily slot per word query (10/day on a non-Premium account, live
  2026-09-30; a paid one costs 10 Stars); out of slots -> exit 3, nothing sent, Stars never spent.
"""


def add_args(p):
    p.add_argument("query", nargs="*", help="words; optional with --chat (then: latest messages matching --from)")
    p.add_argument("--chat", help="one chat: me | id | @username | t.me link | dialog name")
    p.add_argument("--public", action="store_true", help="search posts of all public channels")
    p.add_argument("--from", dest="sender", metavar="USER", help="sender filter (with --chat)")
    p.add_argument("--since", help="7d / 12h / 2w / YYYY-MM-DD / ISO")
    p.add_argument("--until", help="same forms as --since")
    p.add_argument("-n", "--limit", type=int, default=50)
    p.add_argument("--full", action="store_true", help="do not cut message text")


def run(ctx, args):
    query = " ".join(args.query).strip()
    text_limit = None if args.full else ctx.cfg["text_limit"]
    client = ctx.client()
    if args.public:
        if args.chat or args.sender or args.since or args.until:
            raise UsageError("--public takes only a query and -n")
        if not query:
            raise UsageError("--public needs a query")
        rows, flood = messages.search_public(client, query, args.limit, text_limit)
    else:
        chat = peers.resolve(client, args.chat) if args.chat else None
        sender = peers.resolve(client, args.sender) if args.sender else None
        rows, flood = messages.search(client, query, chat, sender, parse_when(args.since), parse_when(args.until),
                                      args.limit, text_limit), None
    ctx.write(rows, messages.MSG_FIELDS + (["link"] if args.public else []))
    if flood is not None:
        left = "free (cached)" if flood.query_is_free else f"{max(flood.remains - 1, 0)}/{flood.total_daily} left today"
        ctx.note(f"public search quota: {left}")
    if any(r["truncated"] for r in rows):
        ctx.note(f"text cut to {text_limit} chars - --full for whole messages")
    if len(rows) >= args.limit:
        ctx.note(f"showing {args.limit}; more may exist - raise -n or narrow with --since/--until")
