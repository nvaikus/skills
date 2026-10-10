"""msg list: inbox conversations, or one listing's conversation with its seller."""
from ...api import account

FIELDS = ["conversation", "from", "last_by", "unread", "when", "subject", "last"]
THREAD = ["from", "day", "time", "text"]
EPILOG = """examples:
  ebay msg list                      # inbox: last_by=them -> the other side answered
  ebay msg list --item 256123456789  # whole conversation with that listing's seller

Inbox rows: kind (-j) member|ebay; when = the site's relative time ('2 Min', 'Gestern').
Thread rows: from = me | the seller's user id; day/time as the site shows them (local time), oldest first.
eBay auto-translates the other side's messages: text = the translation, -j adds translated + original.
"""


def add_args(p):
    p.add_argument("--item", metavar="ID|URL", help="conversation about this listing")
    p.add_argument("--seller", help="seller user id (with --item: skips the listing page)")
    p.add_argument("--limit", type=int, default=25, help="inbox rows (default 25)")
    p.add_argument("--market", help="eBay site (default: config market)")


def run(ctx, args):
    if args.item:
        seller, rows = account.msg_thread(ctx.cfg, account.ref_id(args.item)[0], args.seller, args.market)
        if not rows:
            ctx.note(f"no messages with {seller} about this listing yet")
        ctx.write(rows, THREAD)
        return
    rows = account.msg_inbox(ctx.cfg, args.limit, args.market)
    if not rows:
        ctx.note("inbox is empty")
    ctx.write(rows, FIELDS)
