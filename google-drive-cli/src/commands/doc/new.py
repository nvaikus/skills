"""doc new: create a Google Doc inside an existing Drive folder."""
from ...api import docs
from ...core.stdin import text_arg

FIELDS = ["id", "name", "url", "paragraphs"]
WRITE = True
EPILOG = """examples:
  gdrive doc new /Projects/Meeting-notes
  gdrive doc new "shared:Team/Specs/API v2" $'# API v2\\n\\nDraft.'
  ID=$(gdrive doc new /Projects/Report - --fields id < report.md)

The parent folder must exist. A name already taken in that folder -> exit 3, nothing created
(duplicates make every later path ambiguous). Markdown support: see `gdrive doc edit -h`.
"""


def add_args(p):
    p.add_argument("path", help="/Folder/Name of the new Doc (no .docx)")
    p.add_argument("md", nargs="?", help="initial markdown ('-' = stdin)")


def run(ctx, args):
    f, n = docs.new(ctx.remote, args.path, text_arg(args.md, "MD") if args.md else None, ctx.note)
    ctx.write([{"id": f["id"], "name": f.get("name"), "url": f.get("webViewLink"), "paragraphs": n}],
              FIELDS, receipt=True)
