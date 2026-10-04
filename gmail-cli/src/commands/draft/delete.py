"""draft delete: discard a draft for good (drafts skip Trash)."""
from ...api import compose, drafting, mail

PROFILE = "locate"
WRITE = True
FIELDS = ["profile", "draft_id", "subject"]
EPILOG = """examples:
  gmail draft delete r-1234567890123456789
Only unsent drafts; sent mail goes to Trash with `gmail trash`.
"""


def add_args(p):
    p.add_argument("id", metavar="DRAFT_ID")


def run(ctx, args):
    prof, d = drafting.locate_draft(ctx, args.id)
    subj = mail.headers(d["message"].get("payload")).get("subject", "")
    compose.delete_draft(prof, args.id)
    ctx.write([{"profile": prof, "draft_id": args.id, "subject": subj}], FIELDS, receipt=True)
