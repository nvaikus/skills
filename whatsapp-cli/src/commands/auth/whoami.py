"""whoami: the logged-in account (connects: proves the session is alive)."""
from ...api import auth

FIELDS = auth.ACCOUNT_FIELDS
EPILOG = """examples:
  wa-cli whoami
  wa-cli --account work whoami --fields phone --no-header
"""


def add_args(p):
    pass


def run(ctx, args):
    ctx.write([auth.me_row(ctx.session().me(), ctx.account)], FIELDS, receipt=True)
