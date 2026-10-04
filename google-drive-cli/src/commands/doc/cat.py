"""doc cat: a Google Doc rendered as markdown (headings, lists, bold/italic/code, links, tables)."""
from ...api import address, docs

EPILOG = """examples:
  gdrive doc cat /Projects/Plan
  gdrive doc cat ~/gdrive/Projects/Plan.docx       # the mount's export name works too
  gdrive doc cat "shared:Team/Spec@1AbC..." --tab Appendix
  gdrive doc cat "shared-with-me:/Brief 2026"          # a Doc someone shared with you
  gdrive doc cat /Projects/Plan -j                  # {id, name, url, text}

Read-only view: images show as [image], comments and suggestions are not included.
Multi-tab Docs: the first tab unless --tab (a stderr note lists the others).
"""


def add_args(p):
    p.add_argument("path", help="Drive path, name@id, URL, or a local path inside a mount")
    p.add_argument("--tab", metavar="TITLE", help="tab to read (default: the first)")


def run(ctx, args):
    f, md = docs.cat(ctx.remote, address.of(args.path), args.tab, ctx.note)
    ctx.text(md, {"id": f["id"], "name": f.get("name"), "url": f.get("webViewLink")})
