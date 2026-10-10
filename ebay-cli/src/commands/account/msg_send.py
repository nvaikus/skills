"""msg send: message the seller of a listing."""
import sys

from ...api import account

FIELDS = ["id", "seller", "day", "time", "text"]
EPILOG = """examples:
  ebay msg send 256123456789 "Is it the rev 3.0 board? Ships to Portugal?"
  echo "Are all modules the same part number?" | ebay msg send 256123456789

Sends exactly once (no retry: a rerun sends a second copy - check `ebay msg list --item ID` first).
Verified: exit 0 only when the message shows in the conversation with its time.
Seller = the listing's seller (read from the listing page; --seller skips that page).
"""


def add_args(p):
    p.add_argument("ref", metavar="ID|URL", help="listing id or eBay /itm/ URL")
    p.add_argument("text", nargs="?", help="message; omitted or '-' = read stdin")
    p.add_argument("--seller", help="seller user id (skips the listing page)")
    p.add_argument("--market", help="eBay site (default: config market)")


def run(ctx, args):
    item_id = account.ref_id(args.ref)[0]
    text = account.message_text(args.text, sys.stdin)
    ctx.write([account.msg_send(ctx.cfg, item_id, text, args.seller, args.market)], FIELDS, receipt=True)
