"""profiles: the Google accounts set up on this machine; --default picks the one used without --profile;
--rename moves everything keyed by the name (api/rename)."""
from ...api import mounts, rename
from ...core import config, profile
from ...core.errors import UsageError

PROFILE = "none"
WRITE = True
FIELDS = ["profile", "default", "email", "what", "where", "persist", "mounted"]
EPILOG = """examples:
  gdrive profiles
  gdrive profiles --default work        # used when --profile is not given
  gdrive profiles --rename test work    # dir, default, mount records, caches, services follow

Each profile = one Google account (or one Shared drive) with its own login, mount and index in
~/.claude/gdrive/<profile>/. A new one: gdrive onboard --profile NAME. Commands pick a profile by
--profile, else GDRIVE_PROFILE, else the default, else the only one; a local path inside a mount
always uses the mount's own profile.
--rename refuses (exit 3) while OLD is mounted, syncing, onboarding or indexing: `gdrive umount`
first, `gdrive mount` again after (unuploaded writes stay in the moved cache and resume there).
GDRIVE_PROFILE / scripts naming OLD must be updated by hand.
"""


def add_args(p):
    p.add_argument("--default", metavar="NAME", help="make NAME the default profile")
    p.add_argument("--rename", nargs=2, metavar=("OLD", "NEW"), help="rename profile OLD to NEW")


def run(ctx, args):
    if args.rename:
        old, new = args.rename
        done = rename.rename(old, new)
        ctx.note(f"renamed {old} -> {new}: {done['records']} mount record(s), index service {done['service']}"
                 + (", default profile" if done["default"] else ""))
    names = profile.names()
    if args.default:
        if args.default not in names:
            raise UsageError(f"no profile {args.default!r}; profiles: {', '.join(names) or 'none'}")
        profile.set_default(args.default)
    default = profile.root_config().get("default_profile")
    live = {r.get("profile"): r for r in mounts.records()}
    rows = []
    for n in names:
        cfg = config.load(n)
        m = cfg.get("mount") or {}
        rec = live.get(n)
        rows.append({"profile": n, "default": n == default or len(names) == 1,
                     "email": (cfg.get("account") or {}).get("email"), "what": m.get("what"), "where": m.get("where"),
                     "persist": m.get("persist"), "mounted": bool(rec and mounts.is_mounted(rec)),
                     "project": cfg.get("project_id"), "dir": str(profile.dir(n))})
    if not rows:
        ctx.note("no profiles yet: gdrive onboard --profile NAME")
    ctx.write(rows, FIELDS)
