"""login: sign in once in the ebay browser window; every account command reuses that profile."""
import sys

from ...api import account, browser

FIELDS = ["logged_in", "session", "site"]
EPILOG = """examples:
  ebay login                 # logged in -> one row; else opens the sign-in page, exit 5
  ebay login --market EBAY_GB
  ebay login --keepalive     # scheduled touch: fresh tab, busy browser -> skipped (exit 0), signed out -> exit 5

Exit 5 = the user must sign in in the Chrome window that opened (tell him at once; on a headless server
send the remote-view link from the error, config browser_view_url), then rerun.
Browser: plain Chrome on its own profile (~/.claude/ebay/browser/profiles/<session>), driven by playwright-cli
session 'ebay' over CDP (config browser_session / browser_port). eBay's sign-in cookies are session-only unless
"Stay signed in" is ticked: a Chrome restart signs out. Never asks for or stores the password.
"""


def add_args(p):
    p.add_argument("--market", help="site to sign in on (default: config market)")

    p.add_argument("--keepalive", action="store_true",
                   help="scheduled session touch: check in a fresh tab, leave the user's tab alone; skip when busy")


def run(ctx, args):
    try:
        row = account.login(ctx.cfg, args.market, keepalive=args.keepalive)
    except browser.Busy as e:
        if not args.keepalive:
            raise
        sys.stderr.write(f"# keep-alive skipped: {e}\n")
        return
    ctx.write([row], FIELDS, receipt=True)
