"""login: sign in once in the ebay browser window; every account command reuses that profile."""
from ...api import account

FIELDS = ["logged_in", "session", "site"]
EPILOG = """examples:
  ebay login                 # logged in -> one row; else opens the sign-in page, exit 5
  ebay login --market EBAY_GB

Exit 5 = the user must sign in in the Chrome window that opened (tell him at once), then rerun.
Browser: playwright-cli session 'ebay' (config browser_session / env EBAY_BROWSER_SESSION), headed,
persistent profile; the login survives restarts. Never asks for or stores the password.
"""


def add_args(p):
    p.add_argument("--market", help="site to sign in on (default: config market)")


def run(ctx, args):
    ctx.write([account.login(ctx.cfg, args.market)], FIELDS, receipt=True)
