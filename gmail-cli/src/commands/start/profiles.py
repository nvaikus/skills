"""profiles: the Gmail accounts set up here; --default picks the one used for writes without --profile."""
import shutil

from ...api import auth
from ...core import config, profile
from ...core.errors import UsageError

PROFILE = "none"
WRITE = True
FIELDS = ["profile", "default", "email", "logged_in", "filters", "client_from"]
EPILOG = """examples:
  gmail profiles
  gmail profiles --default work         # used by label/draft/send/-q commands without --profile
  gmail profiles --remove old           # forget a profile (token + config); Gmail itself is untouched

One profile = one Gmail account: ~/.claude/gmail/<profile>/ (config.json, token.json).
search queries every profile unless --profile; an id finds its own profile.
filters = no: the login predates filter support; `gmail --profile NAME onboard --relogin` adds it.
"""


def add_args(p):
    p.add_argument("--default", metavar="NAME", help="make NAME the default profile")
    p.add_argument("--remove", metavar="NAME", help="delete NAME's local login and config")


def run(ctx, args):
    names = profile.names()
    for n in filter(None, (args.default, args.remove)):
        if n not in names:
            raise UsageError(f"no profile {n!r}; profiles: {', '.join(names) or 'none'}")
    if args.remove:
        shutil.rmtree(profile.dir_peek(args.remove))
        if profile.root_config().get("default_profile") == args.remove:
            profile.set_default(None)
        ctx.note(f"removed profile {args.remove} (revoke the app at myaccount.google.com/permissions if wanted)")
        names = profile.names()
    if args.default:
        profile.set_default(args.default)
    default = profile.default()
    rows = []
    for n in names:
        cfg = config.load(n)
        rows.append({"profile": n, "default": n == default, "email": (cfg.get("account") or {}).get("email"),
                     "logged_in": auth.logged_in(n),
                     "filters": auth.logged_in(n) and not auth.lacks_settings(n), "client_from": cfg.get("client_from"),
                     "project": cfg.get("project_id"), "dir": str(profile.dir_peek(n))})
    if not rows:
        ctx.note("no profiles yet: gmail onboard --profile NAME")
    ctx.write(rows, FIELDS)
