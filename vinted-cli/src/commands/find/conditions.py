"""conditions: names + ids for --condition."""
from ...api import filters

FIELDS = ["name", "id", "meaning"]
EPILOG = """examples:
  vinted conditions

Fixed ids on every Vinted site. search --condition takes names or ids, comma-separated.
"""


def add_args(p):
    pass


def run(ctx, args):
    ctx.write([{"name": k, "id": v, "meaning": filters.CONDITION_TEXT[v]} for k, v in filters.CONDITIONS.items()],
              FIELDS)
