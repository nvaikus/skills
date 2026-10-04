"""sheet append: add TSV rows from stdin below the table in a tab."""
from ...api import address, sheets
from ...core.stdin import piped

FIELDS = ["range", "rows", "cols", "cells"]
WRITE = True
EPILOG = """examples:
  printf '2026-09-30\\tBolts\\t12\\n' | gdrive sheet append /Ops/Log
  gdrive sheet append /Ops/Log "Log 2026" < rows.tsv

Rows are inserted after the last row of the tab's data table (new rows, nothing overwritten).
Default tab: the first. Values parse like typing unless --raw. Escapes as in `sheet get`.
"""


def add_args(p):
    p.add_argument("path", help="Drive path, name@id, URL, or a local path inside a mount")
    p.add_argument("tab", nargs="?", help="tab name (default: the first tab)")
    p.add_argument("--raw", action="store_true", help="store values literally (no number/formula parsing)")


def run(ctx, args):
    grid = sheets.parse_tsv(piped("TSV rows"))
    f = sheets.open_sheet(ctx.remote, address.of(args.path))
    ctx.write([sheets.append(ctx.remote, f["id"], args.tab, grid, args.raw)], FIELDS, receipt=True)
