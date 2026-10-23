"""places: city ids by name, or the region list."""
from ...api import olx, query

FIELDS = ["id", "kind", "name", "region", "county"]
EPILOG = """examples:
  olx places ericeira
  olx places --regions
  olx places porto --site pt -j

search --city / --region take a name too (first match is used and noted); use ids in scripts.
--distance KM in search widens --city to a radius.
"""


def add_args(p):
    p.add_argument("query", nargs="*", metavar="NAME", help="city / parish name (prefix ok)")
    p.add_argument("--regions", action="store_true", help="all regions (districts) of the site")
    query.add_site_arg(p)


def run(ctx, args):
    s = olx.site(args.site or ctx.cfg.get("site"))
    q = " ".join(args.query).strip()
    if args.regions or not q:
        rows = [{"id": r.get("id"), "kind": "region", "name": r.get("name"), "region": "", "county": ""}
                for r in olx.regions(s)]
    else:
        rows = [{"id": h["city"]["id"], "kind": "city", "name": h["city"].get("name"),
                 "region": (h.get("region") or {}).get("name"), "county": (h.get("county") or {}).get("name")}
                for h in olx.autocomplete(s, q) if isinstance(h, dict) and h.get("city")]
        if not rows:
            ctx.note(f"no place {q!r} on olx.{s}")
    ctx.write(rows, FIELDS)
