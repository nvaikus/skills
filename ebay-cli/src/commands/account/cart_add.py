"""cart add: put a listing into the cart (never checks out)."""
from ...api import account, query

FIELDS = ["id", "added", "qty", "price", "title"]
EPILOG = """examples:
  ebay cart add 256123456789
  ebay cart add "https://www.ebay.de/itm/256123456789?var=555123" --qty 2
  ebay cart add 256123456789 --variation "Size=L,Colour=Black"   # matched via `ebay item`

Verified: the command reads the cart back; exit 0 only when the item is there.
Already in the cart (no --variation) -> added=no, nothing clicked. Multi-variation listing without a
variation -> exit 2. Only adds; checkout, payment, bids and offers are out of scope.
"""


def add_args(p):
    p.add_argument("ref", metavar="ID|URL", help="listing id, eBay /itm/ URL (?var= kept) or v1|id|var")
    p.add_argument("--qty", type=int, help="quantity (listings with a quantity field)")
    p.add_argument("--variation", metavar="ID|NAME=VALUE,..", help="variation id or aspects, see ebay item")
    p.add_argument("--market", help="eBay site (default: config market)")


def run(ctx, args):
    item_id, var = account.ref_id(args.ref)
    if args.variation:
        var = account.variation_id(item_id, args.variation, query.location(query.flags_of(args), ctx.cfg))
    r = account.cart_add(ctx.cfg, item_id, var, args.qty, args.market)
    if r["already"]:
        ctx.note(f"{item_id} is already in the cart (qty {r['qty']}); nothing changed")
    ctx.write([r], FIELDS, receipt=True)
