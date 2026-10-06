"""media-get: download the media of chosen messages, or of every message in a chat. Read-only on Telegram."""
import os
import tempfile

from ...api import media, peers
from ...core.errors import UsageError
from ...core.timeparse import parse_when

FIELDS = media.GET_FIELDS
EPILOG = """examples:
  tg-cli media-get @ivan 4512                         # -> <tmp>/tg-cli/<original name>, path printed
  tg-cli media-get @ivan 4512 4513 -o ~/Downloads/
  tg-cli media-get "Команда QA" all --type document --since 2026-09-01 -o ./qa/
  tg-cli media-get @ivan all --type photo,video --since 7d --list    # what would be downloaded

WHICH: msg_id(s) from history/search (their text shows '[document: name.pdf]'), or all.
--type: document, photo, video, voice, audio, round, gif, sticker (comma list). all stops at -n
files (note on stderr when more exist). A missing id or one without a file is exit 2, nothing
downloaded. Files keep their original name (photos/voice: <type>_<msg_id>.<ext>); an existing file is
overwritten, a name repeated in one run gets _<msg_id>. Never sends anything, never marks read.
"""


def add_args(p):
    p.add_argument("chat", help="me | id | @username | t.me link | dialog name")
    p.add_argument("which", nargs="+", metavar="WHICH", help="message id(s), or all")
    p.add_argument("-o", "--out", metavar="DIR", help="target directory (default: <tmp>/tg-cli/)")
    p.add_argument("--type", help="with all: only these media types, comma list")
    p.add_argument("--since", help="with all: 7d / 12h / 2w / YYYY-MM-DD / ISO")
    p.add_argument("--until", help="with all: same forms as --since")
    p.add_argument("--from", dest="sender", metavar="USER", help="with all: only this sender")
    p.add_argument("-n", "--limit", type=int, default=50, help="with all: max files (default 50)")
    p.add_argument("--list", action="store_true", help="list the matching media, download nothing")


def _kinds(value):
    if not value:
        return None
    kinds = [k.strip().lower() for k in value.split(",") if k.strip()]
    bad = [k for k in kinds if k not in media.KINDS]
    if bad:
        raise UsageError(f"unknown --type {', '.join(bad)}; use: {', '.join(sorted(media.KINDS))}")
    return kinds


def run(ctx, args):
    bulk = args.which == ["all"]
    if not bulk:
        if not all(w.isdigit() for w in args.which):
            raise UsageError("WHICH: message ids (from history/search) or all")
        if args.type or args.since or args.until or args.sender:
            raise UsageError("--type/--since/--until/--from go with all, not with message ids")
    kinds = _kinds(args.type)
    since, until = parse_when(args.since), parse_when(args.until)
    client = ctx.client()
    chat = peers.resolve(client, args.chat)
    if bulk:
        sender = peers.resolve(client, args.sender) if args.sender else None
        pairs, more = media.scan(client, chat, kinds, since, until, args.limit, sender)
    else:
        pairs, more = media.by_ids(client, chat, [int(w) for w in args.which]), False
    if args.list:
        ctx.write([media.row(m, k) for m, k in pairs], media.LIST_FIELDS)
    else:
        out = os.path.expanduser(args.out or os.path.join(tempfile.gettempdir(), "tg-cli"))
        ctx.write(media.download(client, pairs, out), FIELDS)
    if bulk and not pairs:
        ctx.note("no matching media")
    if more:
        ctx.note(f"stopped at {args.limit} files; more exist - raise -n or narrow with --since/--until/--type")
