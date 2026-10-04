"""filter list: Gmail filters of every profile (or --profile)."""
from ...api import filters, mail

PROFILE = "all"
FIELDS = ["profile", "id", "criteria", "actions"]
EPILOG = """examples:
  gmail filter list
  gmail filter list --profile work -j          # + criteria_raw, action_raw (Gmail's own JSON)

criteria in Gmail query form (from:(x) subject:(y) words); actions: archive, mark-read, never-spam,
trash, star, important, +Label / -Label. Listing works on every login; create/delete may ask for a
re-login (see `gmail filter create -h`).
"""


def add_args(p):
    pass


def run(ctx, args):
    rows, _ = mail.each_profile(filters.list_rows, ctx.profiles, ctx.note)
    if not rows:
        ctx.note(f"no filters in {', '.join(ctx.profiles)}")
    ctx.write(rows, FIELDS)
