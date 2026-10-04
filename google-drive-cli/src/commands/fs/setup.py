"""setup: install the official rclone build into gdrive's own bin dir (no admin, no system rclone)."""
import sys

from ...api import mounts, rclone
from ...core.errors import CliError

PROFILE = "none"  # the rclone binary is shared by all profiles
FIELDS = ["version", "path", "platform", "status"]
WRITE = True
EPILOG = """examples:
  gdrive setup                      # latest rclone for this OS/arch, SHA256-verified
  gdrive setup --version v1.75.1    # pin a version

Installs to ~/.local/share/gdrive/bin (GDRIVE_HOME moves it); a system rclone is never used.
Running mounts keep the old binary until remounted. Re-run to update; same version = no-op.
"""


def add_args(p):
    p.add_argument("--version", dest="want", metavar="vX.Y.Z", help="install this version instead of the latest")
    p.add_argument("--force", action="store_true", help="reinstall even when that version is present")


def run(ctx, args):
    osn, arch = rclone.os_arch()
    have = rclone.installed_version()
    want = args.want or rclone.latest_version()
    if not want.startswith("v"):
        want = "v" + want
    status = "up-to-date"
    if have != want or args.force:
        rclone.install(want)
        got = rclone.installed_version()
        if got != want:
            raise CliError(f"installed binary reports {got!r}, expected {want}")
        status = "installed" if not have else f"updated from {have}" if have != want else "reinstalled"
    if sys.platform.startswith("linux") and mounts.pick_mode("auto")[0] != "mount":
        ctx.note("no FUSE here (/dev/fuse or fusermount3 missing): `gdrive mount` will use a sync folder")
    ctx.write([{"version": want, "path": str(rclone.binary()), "platform": f"{osn}-{arch}", "status": status}],
              FIELDS, receipt=True)

