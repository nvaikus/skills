"""draft list: drafts of every profile (or one with --profile), newest first."""
from ...api import drafting

PROFILE = "all"
FIELDS = ["profile", "draft_id", "date", "to", "subject", "snippet"]
EPILOG = """examples:
  gmail draft list
  gmail draft list --profile work --limit 50
Next: gmail draft show DRAFT_ID.
"""


def add_args(p):
    p.add_argument("--limit", type=int, default=20, metavar="N", help="max rows per profile (default 20)")


def run(ctx, args):
    rows = []
    for prof in ctx.profiles:
        try:
            rows += drafting.list_drafts(prof, args.limit)
        except Exception as e:  # noqa: BLE001 - one logged-out account must not hide the others
            if len(ctx.profiles) == 1:
                raise
            ctx.note(f"profile {prof} skipped: {e}")
    rows.sort(key=lambda r: r["ts"], reverse=True)
    if not rows:
        ctx.note("no drafts")
    ctx.write(rows, FIELDS)
