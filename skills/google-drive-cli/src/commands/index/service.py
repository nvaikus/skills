"""index service: the background updater (every 5 min) for a profile - install or remove."""
from ...api import service
from ...core import profile

FIELDS = ["profile", "service", "unit"]
WRITE = True
EPILOG = """examples:
  gdrive index service              # install/refresh (onboard does this)
  gdrive index service --remove

Linux: systemd user timer (runs while the user has a session; without one the admin enables
`loginctl enable-linger <user>`). macOS: LaunchAgent, every 5 min while logged in.
Windows: not supported - run `gdrive index update` yourself. Rerun after moving the skill or
changing python: the unit pins both paths and the current PATH (for pdftotext).
"""


def add_args(p):
    p.add_argument("--remove", action="store_true", help="stop and uninstall the service")


def run(ctx, args):
    prof = profile.active()
    if args.remove:
        service.remove(prof)
        unit = None
    else:
        unit = service.install(prof)
    ctx.write([{"profile": prof, "service": service.state(prof), "unit": unit}], FIELDS, receipt=True)
