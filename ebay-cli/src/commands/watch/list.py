"""watch list: saved searches."""
from ...api import watch

FIELDS = ["name", "query", "flags", "limit", "seen", "created"]
EPILOG = """examples:
  ebay watch list
  ebay watch list -j

seen = items already recorded for that search (reported once, then only on a price drop).
Files: ~/.claude/ebay/watch/searches.json, watch/seen/<name>.json.
"""


def add_args(p):
    pass


def run(ctx, args):
    rows = [watch.describe(n, w) for n, w in watch.searches().items()]
    if not rows:
        ctx.note('no saved searches: ebay watch add "QUERY" [search flags]')
    ctx.write(rows, FIELDS)
