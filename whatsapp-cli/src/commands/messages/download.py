"""download: media of stored messages (by id, or all in a chat) -> files. Read-only: no receipt, nothing marked read."""
from ...api import media, peers
from ...api.normalize import MEDIA_KINDS
from ...core.errors import UsageError
from ...core.timeparse import parse_when

FIELDS = media.FIELDS
EPILOG = f"""examples:
  wa-cli download +351912345678 3EB0A1B2C3D4E5F6A7B8C9           # -> <tmp>/wa-cli/<original name>
  wa-cli download "Команда QA" 3EB0A1 3EB0B2 -o ./in/
  wa-cli download "Команда QA" all --kind document --since 2025-06-01 --until 2025-07-01 -o ./in/
  wa-cli download "Мама" all --kind image,video -n 10

MSG_ID: the msg_id column of `history` / `search` (media rows read [document] name.pdf, [image] caption...).
all: media of the chat newest first, -n caps it (default 50); --kind {",".join(MEDIA_KINDS)}.
Name: a document keeps its file name; others get <date>_<msg_id>.<ext>. Same name twice in one run ->
"name (2).ext"; an existing file is overwritten. Default dir: the system temp dir + /wa-cli.
status per row: ok | no-keys (stored before wa-cli kept media keys: only a new history sync, i.e.
logout + login, brings them) | expired (gone from WhatsApp's servers: save it from the phone) | failed.
Exit 0 all ok · 2 only no-keys/expired · 1 anything else failed. Other rows still download.
"""


def add_args(p):
    p.add_argument("chat", help="me | +phone | jid | chat/contact name")
    p.add_argument("which", nargs="+", metavar="MSG_ID|all", help="message id(s) from history/search, or all")
    p.add_argument("-o", "--out", metavar="DIR", default=str(media.DEFAULT_DIR), help="target directory (created)")
    p.add_argument("--kind", metavar="K,K", help=f"with all: {','.join(MEDIA_KINDS)}")
    p.add_argument("--since", help="with all: 7d / 2w / YYYY-MM-DD / ISO")
    p.add_argument("--until", help="with all: same forms, exclusive")
    p.add_argument("-n", "--limit", type=int, default=50, help="with all: max messages (default 50)")


def _kinds(value):
    kinds = [k.strip() for k in (value or "").split(",") if k.strip()]
    bad = [k for k in kinds if k not in MEDIA_KINDS]
    if bad:
        raise UsageError(f"--kind {','.join(bad)}: use {','.join(MEDIA_KINDS)}")
    return kinds or None


def run(ctx, args):
    bulk = [w.casefold() for w in args.which] == ["all"]
    if not bulk and (args.kind or args.since or args.until):
        raise UsageError("--kind/--since/--until go with all, not with message ids")
    session = ctx.session()
    store = ctx.store()
    _, chat_jids, _ = peers.resolve(store, args.chat)
    if bulk:
        since, until = parse_when(args.since), parse_when(args.until)
        rows = media.select(store, chat_jids, _kinds(args.kind), since and int(since.timestamp()),
                            until and int(until.timestamp()), args.limit)
    else:
        rows = media.pick(store, chat_jids, args.which)
    if not rows:
        ctx.note("no stored media matches - check with: wa-cli history CHAT --since ...")
        return 0
    results, errors = media.download(session, rows, args.out)
    ctx.write(results, FIELDS)
    if bulk and len(rows) >= args.limit:
        ctx.note(f"stopped at {args.limit}; more may exist - raise -n or narrow with --since/--until/--kind")
    for status, msg in errors.items():
        ctx.note(f"{sum(r['status'] == status for r in results)} {status}: {msg}")
    if not errors:
        return 0
    return 2 if set(errors) <= {"no-keys", "expired"} else 1
