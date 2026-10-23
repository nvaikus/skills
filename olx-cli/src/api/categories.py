"""Category names: the API has ids + counts only; names come from the site's home page state
(window.__PRERENDERED_STATE__.categories.list), cached a week per site."""
import json
import re
import time
import unicodedata

from ..core import paths
from ..core.errors import Broken, UsageError
from . import olx

TTL = 7 * 86400
STATE = re.compile(r'window\.__PRERENDERED_STATE__\s*=\s*("(?:[^"\\]|\\.)*")\s*;')


def _cache(s):
    return paths.root_peek() / "cache" / f"categories-{s}.json"


def parse_home(html):
    m = STATE.search(html)
    if not m:
        raise Broken("OLX home page changed: no __PRERENDERED_STATE__ (category names unavailable; ids still work)")
    try:
        lst = json.loads(json.loads(m.group(1)))["categories"]["list"]
    except (ValueError, KeyError, TypeError) as e:
        raise Broken(f"OLX home page changed: categories state unreadable ({e})") from None
    return {str(c["id"]): {"id": c["id"], "name": c.get("name"), "parent": c.get("parentId") or 0,
                           "path": c.get("path") or "", "level": c.get("level"), "children": c.get("children") or []}
            for c in lst.values() if isinstance(c, dict) and "id" in c}


def tree(s, refresh=False):
    p = _cache(s)
    if not refresh and p.exists() and time.time() - p.stat().st_mtime < TTL:
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            pass
    t = parse_home(olx.home_html(s))
    paths.write_private(p, json.dumps(t, ensure_ascii=False))
    return t


def fold(text):
    t = unicodedata.normalize("NFKD", str(text).lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def label(t, cid):
    c = t.get(str(cid))
    return c["path"] or c["name"] if c else ""


def for_query(s, query, t):
    """-> rows id, name, path, count: categories holding matches for the query, most first."""
    cats = olx.search_categories(s, query).get("categories") or []
    rows = []
    for c in cats:
        node = t.get(str(c.get("id"))) or {}
        rows.append({"id": c.get("id"), "name": node.get("name") or "?", "path": node.get("path") or "",
                     "count": c.get("count"), "level": node.get("level")})
    return rows


def browse(t, under=None, grep=None):
    """No query: level-1 categories, or the children of --under, or names matching --grep anywhere."""
    if grep:
        g = fold(grep)
        nodes = [c for c in t.values() if g in fold(c["name"] or "") or g in fold(c["path"])]
    elif under:
        node = t.get(str(resolve(t, under)))
        nodes = [t[str(k)] for k in node["children"] if str(k) in t]
    else:
        nodes = [c for c in t.values() if c["level"] == 1]
    return [{"id": c["id"], "name": c["name"], "path": c["path"], "count": "", "level": c["level"]}
            for c in sorted(nodes, key=lambda c: (c["level"] or 0, c["path"]))]


def resolve(t, value):
    """id, exact name or path tail ('bicicletas', 'desporto-e-lazer/bicicletas') -> id."""
    v = str(value).strip()
    if v.isdigit():
        return int(v)
    f = fold(v).strip("/")
    hits = [c for c in t.values() if fold(c["name"] or "") == f or fold(c["path"]) == f
            or fold(c["path"]).endswith("/" + f)]
    if len(hits) == 1:
        return hits[0]["id"]
    if not hits:
        raise UsageError(f"no category {value!r}: find ids with `olx categories {value}` or `olx categories --grep {value}`")
    raise UsageError(f"category {value!r} is ambiguous: "
                     + ", ".join(f"{c['id']} {c['path']}" for c in hits[:8]) + "; pass the id")
