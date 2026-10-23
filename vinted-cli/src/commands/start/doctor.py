"""doctor: live check of the page + brand sources, and how often they broke in past runs."""
import time

from ...api import filters, items, query, vinted
from ...core import http, paths
from ...core.errors import CliError

FIELDS = ["check", "ok", "detail"]
EPILOG = """examples:
  vinted doctor
  vinted doctor --site fr --days 7

Checks: site (default from ~/.claude/vinted/config.json, else pt), live search page (one request), brands
API (home page cookie + one JSON request), history = outcomes of every Vinted request in the last --days
(health.tsv: ok / blocked / schema / http / network) with the newest failure.
Exit 3 when Vinted blocks or the page data changed, 1 on other failures.
"""


def add_args(p):
    query.add_site_arg(p)
    p.add_argument("--days", type=int, default=30, metavar="N", help="history window (default 30)")


def _check(rows, name, fn):
    t0 = time.time()
    try:
        detail = fn()
        rows.append({"check": name, "ok": True, "detail": f"{detail} in {time.time() - t0:.1f}s"})
        return None
    except CliError as e:
        rows.append({"check": name, "ok": False, "detail": str(e)})
        return e


def run(ctx, args):
    s = vinted.site(args.site or ctx.cfg.get("site"))
    rows = [{"check": "site", "ok": True, "detail": f"{vinted.SITES[s]} (state {paths.root_peek()})"}]

    def search():
        res, total, _ = items.search(s, {"search_text": "nike"}, 1)
        if not res:
            raise CliError("search returned no rows for 'nike'")
        return f"{total} results"

    def brands():
        return f"{len(filters.brand_rows(s, 'nike'))} brands for 'nike'"

    errs = [e for e in (_check(rows, "search", search), _check(rows, "brands", brands)) if e]
    counts, last = http.health_stats(args.days)
    fails = sum(v for k, v in counts.items() if k != "ok")
    detail = ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "no runs yet"
    if last:
        detail += (f"; last failure {time.strftime('%Y-%m-%d %H:%M', time.localtime(int(last[0])))} {last[3]}: "
                   f"{last[4] if len(last) > 4 else ''}")
    rows.append({"check": f"history {args.days}d", "ok": fails == 0, "detail": detail})
    ctx.write(rows, FIELDS)
    if errs:
        raise errs[0]
