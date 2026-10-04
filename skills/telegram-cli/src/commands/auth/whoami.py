"""whoami: the logged-in account."""
from ...api import auth

FIELDS = ["account", "id", "username", "name", "phone", "premium"]
EPILOG = """examples:
  tg-cli whoami
  tg-cli --account work whoami --fields premium --no-header
"""


def add_args(p):
    pass


def run(ctx, args):
    ctx.write([auth.me_row(ctx.client().get_me(), ctx.account)], FIELDS, receipt=True)
