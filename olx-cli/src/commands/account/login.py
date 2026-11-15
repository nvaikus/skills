"""login: sign in once in the olx browser window; every account command reuses that profile."""
from ...api import account, query

FIELDS = ["logged_in", "session", "site"]
EPILOG = """examples:
  olx login                  # signed in -> one row; else opens OLX's sign-in page, exit 5
  olx login --site pl

Exit 5 = the user signs in in the Chrome window (tell him at once; on a headless server send the remote-view
link from the error, config browser_view_url), then rerun. Never asks for or stores the password.
Browser: plain Chrome on its own profile (~/.claude/olx/browser/profiles/<session>), driven by playwright-cli
session 'olx' over CDP (config browser_session / browser_port); the login survives restarts.
"""


def add_args(p):
    query.add_site_arg(p)


def run(ctx, args):
    ctx.write([account.login(ctx.cfg, query.site({"site": args.site}, ctx.cfg))], FIELDS, receipt=True)
