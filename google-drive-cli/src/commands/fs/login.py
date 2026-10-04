"""login: OAuth installed-app flow; the token lands in gdrive's rclone.conf (shared with mounts)."""
import sys

from ...api import auth, drive, rclone
from ...core import config
from ...core.errors import UsageError

FIELDS = ["profile", "email", "name", "rclone_conf"]
WRITE = True
EPILOG = """examples:
  ! gdrive login                     # user at a terminal: opens nothing, prints a URL, waits
  gdrive login --start               # agent: print the consent URL, give it to the user
  printf '%s' "$REDIRECT_URL" | gdrive login --finish   # the URL the browser landed on

After consent the browser goes to http://127.0.0.1:53682/?code=... . On the same machine the
waiting `gdrive login` catches it; on a headless box the page fails to load - copy that address
bar URL and paste it at the prompt (or pipe it to --finish within ~5 min of allowing).
Needs the profile's OAuth client first (`gdrive onboard` imports it). The token goes to
~/.claude/gdrive/<profile>/rclone.conf; re-login replaces it (another account = another profile).
An External app left in 'Testing' expires tokens after 7 days (onboard detects it and says so).
"""


def add_args(p):
    g = p.add_mutually_exclusive_group()
    g.add_argument("--start", action="store_true", help="print the consent URL and exit (two-step, non-interactive)")
    g.add_argument("--finish", action="store_true", help="read the redirect URL from stdin and store the token")


def _receipt(ctx):
    u = (drive.about(ctx.remote) or {}).get("user", {})
    ctx.write([{"profile": ctx.profile, "email": u.get("emailAddress"), "name": u.get("displayName"),
                "remote": ctx.remote, "rclone_conf": str(rclone.conf())}], FIELDS, receipt=True)


def run(ctx, args):
    cid, secret = config.require_client(ctx.cfg)
    if args.start:
        url = auth.start(ctx.cfg, cid)
        ctx.note("open the URL, consent, then copy the address bar (http://127.0.0.1:53682/?code=...) and run:")
        ctx.note("  printf '%s' '<that URL>' | gdrive login --finish        (within ~5 min of allowing)")
        ctx.write([{"url": url}], ["url"], receipt=True)
        return
    if args.finish:
        code, state = auth.parse_redirect(sys.stdin.read())
        auth.finish(ctx.cfg, cid, secret, code, state)
        return _receipt(ctx)
    if not sys.stdin.isatty():
        raise UsageError("login is interactive: the user runs `! gdrive login` in a terminal; "
                         "an agent uses `gdrive login --start` then `--finish`")
    if auth.logged_in(ctx.remote):
        ctx.note("already logged in - this replaces the stored token")
    url = auth.start(ctx.cfg, cid)
    sys.stderr.write(f"\nOpen this URL in a browser and allow access:\n\n{url}\n\n")
    got = auth.wait_redirect(auth.WAIT_SECONDS, "Waiting for the browser... or paste the redirect URL here: ")
    if not got:
        raise UsageError("no redirect within 10 minutes; run gdrive login again")
    code, state = auth.parse_redirect(got)
    auth.finish(ctx.cfg, cid, secret, code, state)
    sys.stderr.write("\n")
    _receipt(ctx)
