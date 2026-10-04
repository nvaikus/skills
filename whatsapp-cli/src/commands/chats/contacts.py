"""contacts: the phone's address book, as synced to this device."""
from ...api import peers

FIELDS = ["jid", "name", "phone", "push_name"]
EPILOG = """examples:
  wa-cli contacts
  wa-cli contacts иван --fields name,phone

Only people saved in the phone's address book (synced at login, refreshed hourly). Others you
talked to: wa-cli user-find / wa-cli chats.
"""


def add_args(p):
    p.add_argument("filter", nargs="?", help="substring of the name or phone")
    p.add_argument("-n", "--limit", type=int, default=500)
    p.add_argument("--offline", action="store_true", help="store only, no connect")


def run(ctx, args):
    rows = peers.contact_rows(ctx.synced_store(), args.filter, args.limit)
    ctx.write(rows, FIELDS)
    if not rows:
        ctx.note("no address-book contacts in the store" + (f" matching {args.filter!r}" if args.filter else ""))
