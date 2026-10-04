"""profiles: the Apple IDs set up here; --default picks the one used without --profile."""
import os
import shutil

from ...api import tz, when
from ...core import config, profile
from ...core.errors import UsageError

PROFILE = "none"
WRITE = True
FIELDS = ["profile", "default", "apple_id", "password", "default_calendar", "tz", "alarms", "alarms_today"]
EPILOG = """examples:
  icloud-calendar profiles
  icloud-calendar profiles --default work
  icloud-calendar profiles --set-tz Europe/Lisbon   # zone for input/output when not --tz (default: machine zone)
  icloud-calendar profiles --set-alarms 1d,1h --set-alarms-today 2h,1h   # `add` defaults ('' = none)
  icloud-calendar profiles --remove old        # forget local settings; the app password stays valid at Apple

password = set | cmd | missing: whether this environment can supply the app-specific password
(the value itself is never shown). missing -> `icloud-calendar onboard --profile NAME`.
"""


def add_args(p):
    p.add_argument("--default", metavar="NAME", help="make NAME the default profile")
    p.add_argument("--remove", metavar="NAME", help="delete NAME's local config")
    p.add_argument("--set-alarms", metavar="LIST", help="default alerts for `add`, e.g. 1d,1h ('' = none)")
    p.add_argument("--set-alarms-today", metavar="LIST",
                   help="default alerts for events starting today, e.g. 2h,1h ('' = same as --set-alarms)")
    p.add_argument("--set-tz", metavar="ZONE", help="store an IANA zone for the selected/default profile ('' = machine zone)")


def run(ctx, args):
    names = profile.names()
    for n in filter(None, (args.default, args.remove)):
        if n not in names:
            raise UsageError(f"no profile {n!r}; profiles: {', '.join(names) or 'none'}")
    if args.remove:
        shutil.rmtree(profile.dir_peek(args.remove))
        if profile.root_config().get("default_profile") == args.remove:
            profile.set_default(None)
        ctx.note(f"removed profile {args.remove} (revoke its app-specific password at account.apple.com if wanted)")
        names = profile.names()
    if args.default:
        profile.set_default(args.default)
    if args.set_tz is not None:
        target = args.profile or profile.default()
        if not target:
            raise UsageError("--set-tz: pass --profile NAME")
        if args.set_tz:
            try:
                tz.zone(args.set_tz)
            except KeyError:
                raise UsageError(f"unknown time zone {args.set_tz!r}: use an IANA name like Europe/Lisbon") from None
        config.update(target, tz=args.set_tz or None)
    for flag, key in (("set_alarms", "default_alarms"), ("set_alarms_today", "default_alarms_today")):
        val = getattr(args, flag)
        if val is None:
            continue
        target = args.profile or profile.default()
        if not target:
            raise UsageError(f"--{flag.replace('_', '-')}: pass --profile NAME")
        items = [a.strip() for a in val.split(",") if a.strip()]
        for a in items:
            try:
                when.alarm(a)
            except Exception:
                raise UsageError(f"bad alert {a!r}: use 10m, 1h, 1d, 0") from None
        config.update(target, **{key: items if items or key == "default_alarms" else None})
    default = profile.default()
    rows = []
    for n in names:
        cfg = config.load(n)
        pw = ("set" if os.environ.get(cfg.get("password_env") or "") else "cmd" if cfg.get("password_cmd") else "missing")
        rows.append({"profile": n, "default": n == default,
                     "apple_id": os.environ.get(cfg.get("apple_id_env") or "") or cfg.get("apple_id"),
                     "password": pw, "password_env": cfg.get("password_env"),
                     "default_calendar": cfg.get("default_calendar"), "tz": cfg.get("tz"),
                     "alarms": ",".join(cfg.get("default_alarms") or []),
                     "alarms_today": ",".join(cfg.get("default_alarms_today") or []),
                     "home": cfg.get("home"), "dir": str(profile.dir_peek(n))})
    if not rows:
        ctx.note("no profiles yet: icloud-calendar onboard")
    ctx.write(rows, FIELDS)
