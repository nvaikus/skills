"""sheet get: cell values of a range as TSV (a grid, no header of ours)."""
from ...api import address, sheets

EPILOG = """examples:
  gdrive sheet get /Finance/Budget                  # whole first tab
  gdrive sheet get /Finance/Budget "Q3!A1:F20"
  gdrive sheet get /Finance/Budget "Q3 plan" | head -5   # a tab name alone = the whole tab
  gdrive sheet get /Finance/Budget A:A --render formula -j   # JSON array of rows

Row 1 is the sheet's own first row. Trailing empty cells/rows are omitted by Google, so rows
can be ragged. Cells escape tab, newline and backslash as \\t \\n \\\\ - the same format
`sheet set` reads, so get -> edit -> set round-trips.
"""


def add_args(p):
    p.add_argument("path", help="Drive path, name@id, URL, or a local path inside a mount")
    p.add_argument("range", nargs="?", help="A1 range: Tab!A1:C9, A1:C9 (first tab) or a tab name")
    p.add_argument("--render", choices=sorted(sheets.RENDER), default="formatted",
                   help="formatted (as shown, default) · raw (numbers unformatted) · formula")


def run(ctx, args):
    f = sheets.open_sheet(ctx.remote, address.of(args.path))
    rng, grid = sheets.get(ctx.remote, f["id"], args.range, args.render)
    ctx.note(f"{rng}: {len(grid)} row(s)")
    ctx.grid(grid)
