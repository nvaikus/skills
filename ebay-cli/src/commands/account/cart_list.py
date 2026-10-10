"""cart list: what is in the user's eBay cart."""
from ...api import account

FIELDS = ["id", "qty", "price", "shipping", "seller", "title"]
EPILOG = """examples:
  ebay cart list
  ebay cart list -j          # + variation

price/shipping are the site's display strings (currency as shown, e.g. 'US $116,78').
seller = the cart's seller label (store name), not always the user id.
"""


def add_args(p):
    p.add_argument("--market", help="eBay site (default: config market)")


def run(ctx, args):
    rows = account.cart_list(ctx.cfg, args.market)
    if not rows:
        ctx.note("cart is empty")
    ctx.write(rows, FIELDS)
