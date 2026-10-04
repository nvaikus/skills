"""user-find: people and chats by name or phone; --check asks WhatsApp whether a number has an account."""
from ...api import peers
from ...core.errors import UsageError

FIELDS = peers.PEER_FIELDS + ["source"]
EPILOG = """examples:
  wa-cli user-find "Иван Петров"
  wa-cli user-find 912345               # phone fragment
  wa-cli user-find +351912345678 --check   # is this number on WhatsApp? (one request)

source: contact (address book) · chat (a chat in the store) · seen (sender seen in a group) ·
whatsapp (--check: registered, not yet in the store). WhatsApp has no people search by name:
names match only what this device has seen.
"""


def add_args(p):
    p.add_argument("query", help="name or phone fragment")
    p.add_argument("--check", action="store_true", help="the query is a full phone number: ask WhatsApp if it is registered")
    p.add_argument("-n", "--limit", type=int, default=20)
    p.add_argument("--offline", action="store_true", help="store only, no connect")


def run(ctx, args):
    if args.check:
        if not peers.PHONE_RE.fullmatch(args.query.strip()):
            raise UsageError("--check needs a full phone number in international format (+351912345678)")
        res = ctx.session().on_whatsapp("+" + "".join(c for c in args.query if c.isdigit()))
        names = peers.Names(ctx.store())
        rows = [names.row(r["jid"], source="whatsapp") for r in res if r["is_in"] and r["jid"]]
        ctx.write(rows, FIELDS)
        if not rows:
            ctx.note(f"{args.query} is not on WhatsApp")
        return
    rows = peers.find(ctx.synced_store(), args.query, args.limit)
    ctx.write(rows, FIELDS)
    if not rows:
        ctx.note(f"nothing found for {args.query!r}" + (" - for a full number try --check"
                                                         if peers.PHONE_RE.fullmatch(args.query.strip()) else ""))
