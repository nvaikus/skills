"""sheet new: create a Google Sheet inside an existing Drive folder."""
from ...api import sheets
from ...core.stdin import piped

FIELDS = ["id", "name", "url", "cells"]
WRITE = True
EPILOG = """examples:
  gdrive sheet new /Ops/Stock
  printf 'Name\\tQty\\n' | gdrive sheet new /Ops/Stock --tsv     # filled from A1

The parent folder must exist. A name already taken in that folder -> exit 3, nothing created.
"""


def add_args(p):
    p.add_argument("path", help="/Folder/Name of the new Sheet (no .xlsx)")
    p.add_argument("--tsv", action="store_true", help="fill from stdin TSV starting at A1")


def run(ctx, args):
    grid = sheets.parse_tsv(piped("TSV rows")) if args.tsv else None
    f = sheets.new(ctx.remote, args.path)
    cells = sheets.put(ctx.remote, f["id"], "A1", grid, False)["cells"] if grid else 0
    ctx.write([{"id": f["id"], "name": f.get("name"), "url": f.get("webViewLink"), "cells": cells}],
              FIELDS, receipt=True)
