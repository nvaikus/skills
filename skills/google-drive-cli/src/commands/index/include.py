"""index include: also index Shared with me, all Shared drives, or one Shared drive (what=/ profiles)."""
from ...api import sections

FIELDS = ["profile", "section", "status", "files", "pending"]
WRITE = True
EPILOG = """examples:
  gdrive index include shared-with-me          # files others shared with this account
  gdrive index include shared-drives           # every Shared drive
  gdrive index include "shared:Team Drive"     # one Shared drive
  gdrive index status --fields profile,sections

By default only My Drive is indexed; the mount shows every section anyway (read files there or
by address). Include a section when the user talks about files shared with them / a Shared drive,
or when a search finds nothing and the file may live there. Metadata is listed at once (files =
how many), the texts are extracted in the background - search works for the finished part.
Undo: `gdrive index exclude SECTION` (its texts are deleted). Only for profiles mounting /.
"""


def add_args(p):
    p.add_argument("section", help="shared-with-me | shared-drives | shared:<Drive>")


def run(ctx, args):
    sections.require_everything(ctx.cfg)
    sec = sections.normalize(ctx.remote, args.section)
    ctx.write([sections.change(ctx.cfg, sec, True, ctx.note)], FIELDS, receipt=True)
