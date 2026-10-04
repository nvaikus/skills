"""index exclude: stop indexing a section added with `index include` (its texts are deleted)."""
from ...api import sections

FIELDS = ["profile", "section", "status", "deleted"]
WRITE = True
EPILOG = """examples:
  gdrive index exclude shared-with-me
  gdrive index exclude "shared:Team Drive"

The section stays visible in the mount; only its index texts go. My Drive is always indexed.
"""


def add_args(p):
    p.add_argument("section", help="shared-with-me | shared-drives | shared:<Drive>")


def run(ctx, args):
    sections.require_everything(ctx.cfg)
    sec = sections.normalize(ctx.remote, args.section)
    ctx.write([sections.change(ctx.cfg, sec, False, ctx.note)], FIELDS, receipt=True)
