"""colors: names + ids for --color."""
from ...api import filters

FIELDS = ["name", "id"]
EPILOG = """examples:
  vinted colors

Fixed ids on every Vinted site. search --color takes names or ids, comma-separated.
"""


def add_args(p):
    pass


def run(ctx, args):
    ctx.write([{"name": k, "id": v} for k, v in filters.COLORS.items()], FIELDS)
