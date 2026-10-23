"""watch list: saved searches."""
from ...api import watch

FIELDS = ["name", "site", "query", "flags", "limit", "seen", "created"]
EPILOG = """examples:
  olx watch list
  olx watch list -j

seen = listings already recorded for that search (reported once, then only on a price drop).
Files: ~/.claude/olx/watch/searches.json, watch/seen/<name>.json.
"""


def add_args(p):
    pass


def run(ctx, args):
    rows = [watch.describe(n, w) for n, w in watch.searches().items()]
    if not rows:
        ctx.note('no saved searches: olx watch add "QUERY" [search flags]')
    ctx.write(rows, FIELDS)
