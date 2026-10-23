"""Filter ids: conditions and colors (fixed Vinted-wide ids, names live-checked on vinted.pt 2026-10-23),
brands (JSON API), sizes (per category, read back from a catalog page's selected-filter state)."""
import json
import time

from ..core import paths
from ..core.errors import Broken, UsageError
from . import categories, vinted

CONDITIONS = {"new-tags": 6, "new": 1, "very-good": 2, "good": 3, "satisfactory": 4}
CONDITION_TEXT = {6: "new with tags", 1: "new without tags", 2: "very good", 3: "good", 4: "satisfactory"}
COLORS = {"black": 1, "grey": 3, "white": 12, "cream": 20, "beige": 4, "apricot": 21, "orange": 11, "coral": 22,
          "red": 7, "burgundy": 23, "fuchsia": 5, "pink": 24, "purple": 6, "lilac": 25, "light-blue": 26, "blue": 9,
          "navy": 27, "turquoise": 17, "mint": 30, "green": 10, "dark-green": 28, "khaki": 16, "brown": 2,
          "mustard": 29, "yellow": 8, "silver": 13, "gold": 14, "multi": 15, "clear": 32}
SIZE_MAX = 2000      # size ids probed by `sizes` (live max seen ~1700)
SIZE_CHUNK = 350     # ids per probe request: ~19 KB of query string gets HTTP 431
SIZE_TTL = 30 * 86400


def ids(value, table, what, cmd):
    """'good,3,new-tags' -> [3, 3, 6] (names from `table`, numbers pass through), deduplicated in order."""
    out = []
    for v in str(value).replace(" ", ",").split(","):
        v = v.strip().lower()
        if not v:
            continue
        if v.isdigit():
            i = int(v)
        elif v in table:
            i = table[v]
        else:
            raise UsageError(f"unknown {what} {v!r}: one of {', '.join(table)} or an id (`vinted {cmd}`)")
        if i not in out:
            out.append(i)
    return out


def brand_rows(s, keyword):
    return [{"id": b.get("id"), "name": b.get("title"), "items": b.get("item_count"), "slug": b.get("slug")}
            for b in vinted.brands(s, keyword) if isinstance(b, dict)]


def brand_ids(s, value, note=None):
    """'nike,53,the north face' -> ids; a name takes the exact (case-folded) title match, else the top hit."""
    out = []
    for v in str(value).split(","):
        v = v.strip()
        if not v:
            continue
        if v.isdigit():
            out.append(int(v))
            continue
        rows = brand_rows(s, v)
        if not rows:
            raise UsageError(f"no brand {v!r} on {vinted.SITES[s]}: try `vinted brands {v}`")
        hit = next((r for r in rows if categories.fold(r["name"] or "") == categories.fold(v)), rows[0])
        if note:
            note(f"brand {v!r} = {hit['name']} (id {hit['id']})")
        out.append(int(hit["id"]))
    return out


def _sizes_cache(s, cat):
    return paths.root_peek() / "cache" / f"sizes-{s.replace('.', '-')}-{cat}.json"


def _options(fl, ftype):
    box = vinted.extract(fl, '"dynamicFilters":{"dynamicFilters":', "filters", at=len('"dynamicFilters":'))
    flt = next((f for f in box.get("dynamicFilters") or [] if isinstance(f, dict) and f.get("type") == ftype), None)
    if flt is None:
        raise Broken(f"Vinted page data changed: no {ftype} filter in dynamicFilters")
    return flt.get("options") or []


def _leaves(opts, trail=()):
    """Option tree (top group > group > size) -> (leaf, [ancestor titles]); leaves have numeric ids."""
    for o in opts:
        if not isinstance(o, dict):
            continue
        kids = o.get("options") or []
        if kids:
            yield from _leaves(kids, trail + (str(o.get("title")),))
        elif str(o.get("id")).isdigit():
            yield {**o, "id": int(o["id"])}, list(trail)


def sizes(s, cat, refresh=False):
    """-> rows id, group, name for a category: probes size ids 1..SIZE_MAX in chunks as selected filters and
    reads the titles Vinted echoes back (grouped). Cached a month per site + category."""
    p = _sizes_cache(s, cat)
    if not refresh and p.exists() and time.time() - p.stat().st_mtime < SIZE_TTL:
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            pass
    rows, seen = [], set()
    for start in range(1, SIZE_MAX + 1, SIZE_CHUNK):
        params = {"catalog[]": cat, "size_ids[]": list(range(start, min(start + SIZE_CHUNK, SIZE_MAX + 1)))}
        for leaf, trail in _leaves(_options(vinted.catalog_page(s, params), "size")):
            if leaf["id"] not in seen:
                seen.add(leaf["id"])
                rows.append({"id": leaf["id"], "group": " > ".join(trail), "name": leaf.get("title")})
    paths.write_private(p, json.dumps(rows, ensure_ascii=False))
    return rows
