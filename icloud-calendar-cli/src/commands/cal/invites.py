"""invites: share invitations waiting in the notification collection (read-only)."""
from ...api import invites

FIELDS = ["calendar", "from", "access", "status", "uid"]
EPILOG = """examples:
  icloud-calendar invites

Read-only: accept or decline in Calendar on a Mac/iPhone or at icloud.com. An accepted share then
shows in `icloud-calendar calendars` as kind shared-with-me.
"""


def add_args(p):
    pass


def run(ctx, args):
    s = ctx.session()
    rows = invites.pending(s, ctx.cfg)
    if not rows:
        ctx.note("no pending share invitations")
    ctx.write(rows, FIELDS)
