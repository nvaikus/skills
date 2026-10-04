"""label rename: rename a label and every label nested under it."""
from ...api import mail

WRITE = True
FIELDS = ["old", "new"]
EPILOG = """examples:
  gmail label rename Clients/Acme Archive/Acme     # Clients/Acme/2025 -> Archive/Acme/2025 too
Messages keep the label (same id). System labels cannot be renamed.
"""


def add_args(p):
    p.add_argument("old", metavar="OLD")
    p.add_argument("new", metavar="NEW")


def run(ctx, args):
    moves = mail.rename_label(ctx.profile, args.old, args.new)
    ctx.write([{"old": o, "new": n} for o, n in moves], FIELDS)
