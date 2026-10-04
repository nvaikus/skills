"""login: OAuth installed-app flow for one profile (onboard prints the URL and the --finish line)."""
import sys

from ...api import auth, mail
from ...core import config
from ...core.errors import UsageError

FIELDS = ["profile", "email", "messages"]
WRITE = True
EPILOG = """examples:
  gmail --profile work login --start             # print the consent URL (onboard does this for you)
  printf '%s' "$REDIRECT_URL" | gmail --profile work login --finish
  ! gmail --profile work login                   # user at a terminal: waits for the browser

After consent the browser goes to http://127.0.0.1:53682/?code=... ; on another machine that page
fails to load - the user copies that address. Pipe it to --finish within ~5 min of allowing. Exit 2 "box
unticked" = the Gmail checkbox on Google's consent page was left empty: run onboard again.
"""


def add_args(p):
    g = p.add_mutually_exclusive_group()
    g.add_argument("--start", action="store_true", help="print the consent URL and exit")
    g.add_argument("--finish", action="store_true", help="read the redirect URL from stdin and store the token")


def _receipt(ctx, prof):
    if auth.lacks_settings(prof):
        ctx.note("the settings-and-filters box was left unticked: mail works, `gmail filter create/delete` will not "
                 f"(`gmail --profile {prof} onboard --relogin` to add it)")
    st = mail.mailbox(prof)
    ctx.write([{"profile": prof, "email": st.get("emailAddress"), "messages": st.get("messagesTotal")}],
              FIELDS, receipt=True)


def run(ctx, args):
    prof = ctx.profile
    cid, _ = config.require_client(ctx.cfg, prof)
    if args.start:
        url = auth.start(prof, cid)
        ctx.note(f"open the URL, consent, copy the address bar, then: printf '%s' '<URL>' | gmail --profile {prof} login --finish")
        ctx.write([{"url": url}], ["url"], receipt=True)
        return
    if args.finish:
        code, state = auth.parse_redirect(sys.stdin.read())
        auth.finish(prof, ctx.cfg, code, state)
        return _receipt(ctx, prof)
    if not sys.stdin.isatty():
        raise UsageError("login is interactive: an agent uses `gmail onboard` (or login --start / --finish)")
    url = auth.start(prof, cid)
    sys.stderr.write(f"\nOpen this URL in a browser and allow access:\n\n{url}\n\n")
    got = auth.wait_redirect(auth.WAIT_SECONDS, "Waiting for the browser... or paste the redirect URL here: ")
    if not got:
        raise UsageError("no redirect within 10 minutes; run gmail login again")
    code, state = auth.parse_redirect(got)
    auth.finish(prof, ctx.cfg, code, state)
    _receipt(ctx, prof)
