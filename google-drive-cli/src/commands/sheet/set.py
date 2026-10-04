"""sheet set: overwrite a range with TSV rows from stdin."""
from ...api import address, sheets
from ...core.stdin import piped

FIELDS = ["range", "rows", "cols", "cells"]
WRITE = True
EPILOG = """examples:
  printf 'Name\\tQty\\nBolts\\t12\\n' | gdrive sheet set /Ops/Stock "Stock!A1"
  gdrive sheet get /Ops/Stock B2:B9 > col.tsv; ...; gdrive sheet set /Ops/Stock B2:B9 < col.tsv

OVERWRITES the cells the rows cover, starting at the range's top-left - read them first with
`sheet get`. Values are parsed like typing (12 -> number, =SUM(A:A) -> formula) unless --raw.
Empty TSV cells clear the cell. Escapes \\t \\n \\\\ as in `sheet get`.
"""


def add_args(p):
    p.add_argument("path", help="Drive path, name@id, URL, or a local path inside a mount")
    p.add_argument("range", help="top-left cell or A1 range, e.g. Tab!B2 or Tab!B2:D9")
    p.add_argument("--raw", action="store_true", help="store values literally (no number/formula parsing)")


def run(ctx, args):
    grid = sheets.parse_tsv(piped("TSV rows"))
    f = sheets.open_sheet(ctx.remote, address.of(args.path))
    ctx.write([sheets.put(ctx.remote, f["id"], args.range, grid, args.raw)], FIELDS, receipt=True)
