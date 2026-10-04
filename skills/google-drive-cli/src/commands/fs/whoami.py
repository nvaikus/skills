"""whoami: which Google account the stored token belongs to, and where gdrive keeps things."""
from ...api import drive, rclone

FIELDS = ["profile", "email", "name", "used", "limit", "rclone", "rclone_conf"]
EPILOG = """examples:
  gdrive whoami
  gdrive whoami --fields email --no-header

Exit 2 = not logged in or no profile (gdrive onboard). limit is empty for unlimited plans.
"""


def add_args(p):
    pass


def _gb(v):
    return f"{int(v) / 1e9:.1f}G" if v not in (None, "") else None


def run(ctx, args):
    a = drive.about(ctx.remote) or {}
    u, q = a.get("user", {}), a.get("storageQuota", {})
    ctx.write([{"profile": ctx.profile, "email": u.get("emailAddress"), "name": u.get("displayName"), "used": _gb(q.get("usage")),
                "limit": _gb(q.get("limit")), "remote": ctx.remote,
                "rclone": rclone.installed_version(), "rclone_conf": str(rclone.conf())}], FIELDS)
