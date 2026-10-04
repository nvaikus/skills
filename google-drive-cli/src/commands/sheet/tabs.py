"""sheet tabs: the tabs of a Google Sheet."""
from ...api import address, sheets

FIELDS = ["tab", "rows", "cols", "hidden", "id"]
EPILOG = """examples:
  gdrive sheet tabs /Finance/Budget
  gdrive sheet tabs ~/gdrive/Finance/Budget.xlsx --fields tab --no-header

rows/cols = grid size (allocated cells), not how many hold data.
"""


def add_args(p):
    p.add_argument("path", help="Drive path, name@id, URL, or a local path inside a mount")


def run(ctx, args):
    f = sheets.open_sheet(ctx.remote, address.of(args.path))
    ctx.write(sheets.tabs(ctx.remote, f["id"]), FIELDS)
