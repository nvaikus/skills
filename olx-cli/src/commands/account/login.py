"""login: sign in once in the olx browser window; every account command reuses that profile."""
import sys

from ...api import account, browser, query

FIELDS = ["logged_in", "session", "site"]
EPILOG = """examples:
  olx login                  # signed in -> one row; else opens OLX's sign-in page, exit 5
  olx login --site pl
  olx login --keepalive      # scheduled touch: fresh tab, busy browser -> skipped (exit 0), signed out -> exit 5

Exit 5 = the user signs in in the Chrome window (tell him at once; on a headless server send the remote-view
link from the error, config browser_view_url), then rerun. Never asks for or stores the password.
Browser: plain Chrome on its own profile (~/.claude/olx/browser/profiles/<session>), driven by playwright-cli
session 'olx' over CDP (config browser_session / browser_port); the login survives restarts.
"""


def add_args(p):
    query.add_site_arg(p)
    p.add_argument("--keepalive", action="store_true",
                   help="scheduled session touch: check in a fresh tab, leave the user's tab alone; skip when busy")


def run(ctx, args):
    try:
        row = account.login(ctx.cfg, query.site({"site": args.site}, ctx.cfg), keepalive=args.keepalive)
    except browser.Busy as e:
        if not args.keepalive:
            raise
        sys.stderr.write(f"# keep-alive skipped: {e}\n")
        return
    ctx.write([row], FIELDS, receipt=True)
