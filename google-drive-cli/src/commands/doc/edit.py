"""doc edit: targeted changes that keep everything else (comments, formatting) intact."""
from ...api import address, docs
from ...core.errors import UsageError
from ...core.stdin import text_arg

FIELDS = ["id", "name", "action", "changed", "url"]
WRITE = True
EPILOG = """examples:
  gdrive doc edit /Projects/Plan --replace "Q3 launch" "Q4 launch"
  gdrive doc edit /Projects/Plan --append $'## Risks\\n- vendor delay'
  gdrive doc edit /Projects/Plan --after "Open questions" - < notes.md

--replace: exact, case-sensitive, ALL occurrences, every tab (or --tab); 0 found -> exit 2.
--append: markdown at the end. --after H: at the END of section H (before the next heading of
the same or a higher level). Markdown: # headings, - / 1. lists (indent = nesting), **bold**,
*italic*, `code`, [text](url), ``` fences. Tables go in as plain lines, --- is dropped.
There is no full rewrite on purpose: re-uploading a Doc loses comments and formatting.
Re-read with `gdrive doc cat` to verify.
"""


def add_args(p):
    p.add_argument("path", help="Drive path, name@id, URL, or a local path inside a mount")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--replace", nargs=2, metavar=("OLD", "NEW"), help="replace every exact occurrence")
    g.add_argument("--append", metavar="MD", help="markdown to add at the end ('-' = stdin)")
    g.add_argument("--after", nargs=2, metavar=("HEADING", "MD"), help="markdown to add at the end of a section")
    p.add_argument("--tab", metavar="TITLE", help="limit to one tab of a multi-tab Doc")


def run(ctx, args):
    addr = address.of(args.path)
    if args.replace:
        old, new = args.replace
        if not old:
            raise UsageError("OLD is empty")
        f, n = docs.replace(ctx.remote, addr, old, new, args.tab)
        if not n:
            raise UsageError(f"{old!r} does not occur in {f.get('name')!r} (exact, case-sensitive) - nothing changed")
        row = {"action": "replace", "changed": f"{n} occurrence(s)"}
    else:
        heading, md = (args.after if args.after else (None, args.append))
        f, n, where = docs.insert(ctx.remote, addr, text_arg(md, "MD"), heading, args.tab, ctx.note)
        row = {"action": "append" if heading is None else "after", "changed": f"{n} paragraph(s) at {where}"}
    ctx.write([{"id": f["id"], "name": f.get("name"), **row, "url": f.get("webViewLink")}], FIELDS, receipt=True)
