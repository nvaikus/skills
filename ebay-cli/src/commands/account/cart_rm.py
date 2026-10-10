"""cart rm: remove listings from the cart."""
from ...api import account

FIELDS = ["id", "removed"]
EPILOG = """examples:
  ebay cart rm 256123456789
  ebay cart rm 256123456789 117000000001

Removes every cart line of each id (all variations), then reloads the cart to verify.
removed=0: the id was not in the cart.
"""


def add_args(p):
    p.add_argument("ids", nargs="+", metavar="ID|URL")
    p.add_argument("--market", help="eBay site (default: config market)")


def run(ctx, args):
    ids = [account.ref_id(r)[0] for r in args.ids]
    results, left = account.cart_rm(ctx.cfg, ids, args.market)
    ctx.note(f"cart now has {len(left)} line(s)")
    ctx.write(results, FIELDS)
