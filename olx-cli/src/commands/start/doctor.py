"""doctor: live endpoint check + how often it broke in past runs."""
import time

from ...api import offers, olx, query
from ...core import http, paths
from ...core.errors import CliError

FIELDS = ["check", "ok", "detail"]
EPILOG = """examples:
  olx doctor
  olx doctor --site pl --days 7

Checks: site (default from ~/.claude/olx/config.json, else pt), live search (one request), history =
outcomes of every OLX request in the last --days (health.tsv: ok / blocked / schema / http / network)
with the newest failure. Exit 3 when OLX blocks or the JSON changed, 1 on other failures.
"""


def add_args(p):
    query.add_site_arg(p)
    p.add_argument("--days", type=int, default=30, metavar="N", help="history window (default 30)")


def run(ctx, args):
    s = olx.site(args.site or ctx.cfg.get("site"))
    rows = [{"check": "site", "ok": True, "detail": f"{olx.SITES[s]} (state {paths.root_peek()})"}]
    err = None
    t0 = time.time()
    try:
        res, total, _ = offers.search(s, {"query": "bicicleta" if s == "pt" else "iphone"}, 1)
        rows.append({"check": "search", "ok": bool(res), "detail": f"{total} results in {time.time() - t0:.1f}s"})
    except CliError as e:
        err = e
        rows.append({"check": "search", "ok": False, "detail": str(e)})
    counts, last = http.health_stats(args.days)
    fails = sum(v for k, v in counts.items() if k != "ok")
    detail = ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "no runs yet"
    if last:
        detail += f"; last failure {time.strftime('%Y-%m-%d %H:%M', time.localtime(int(last[0])))} {last[3]}: {last[4] if len(last) > 4 else ''}"
    rows.append({"check": f"history {args.days}d", "ok": fails == 0, "detail": detail})
    ctx.write(rows, FIELDS)
    if err:
        raise err
