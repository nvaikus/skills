"""Category (catalog) tree: from any catalog page's flight state (`"catalogTree":[{id,title,url,catalogs}]`),
cached a week per site. Flattened to {id: {id, name, path, parent, level, children}}."""
import json
import time
import unicodedata

from ..core import paths
from ..core.errors import Broken, UsageError
from . import vinted

TTL = 7 * 86400


def _cache(s):
    return paths.root_peek() / "cache" / f"categories-{s.replace('.', '-')}.json"


def flatten(nodes):
    out = {}

    def walk(lst, parent, trail, level):
        for c in lst or []:
            if not isinstance(c, dict) or "id" not in c:
                continue
            path = trail + [c.get("title") or "?"]
            kids = c.get("catalogs") or []
            out[str(c["id"])] = {"id": c["id"], "name": c.get("title"), "path": " > ".join(path), "parent": parent,
                                 "level": level, "children": [k["id"] for k in kids if isinstance(k, dict)],
                                 "slug": (c.get("url") or "").rsplit("/", 1)[-1]}
            walk(kids, c["id"], path, level + 1)
    walk(nodes, 0, [], 1)
    return out


def tree(s, refresh=False, fl=None):
    p = _cache(s)
    if not refresh and fl is None and p.exists() and time.time() - p.stat().st_mtime < TTL:
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            pass
    fl = fl if fl is not None else vinted.catalog_page(s, {"search_text": ""})
    nodes = vinted.extract(fl, '"catalogTree":', "category tree")
    if not isinstance(nodes, list) or not nodes:
        raise Broken("Vinted page data changed: catalogTree is empty or not a list")
    t = flatten(nodes)
    paths.write_private(p, json.dumps(t, ensure_ascii=False))
    return t


def fold(text):
    t = unicodedata.normalize("NFKD", str(text).lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def browse(t, under=None, grep=None):
    """Top level, or the children of --under, or names/paths/slugs containing every --grep word, all levels."""
    if grep:
        words = fold(grep).split()
        nodes = [c for c in t.values() if all(w in fold(c["path"] + " " + c.get("slug", "")) for w in words)]
    elif under:
        node = t.get(str(resolve(t, under)))
        nodes = [t[str(k)] for k in node["children"] if str(k) in t]
    else:
        nodes = [c for c in t.values() if c["level"] == 1]
    return [{"id": c["id"], "name": c["name"], "path": c["path"], "level": c["level"]}
            for c in sorted(nodes, key=lambda c: (c["level"], c["path"]))]


def resolve(t, value):
    """id, exact name, slug ('1231-shoes' or 'shoes') or path tail ('Homem > Calçado') -> id."""
    v = str(value).strip()
    if v.isdigit():
        return int(v)
    f = fold(v)
    hits = [c for c in t.values() if f in (fold(c["name"] or ""), fold(c.get("slug", "")),
                                         fold(c.get("slug", "")).split("-", 1)[-1])
            or fold(c["path"]).endswith(f) and (fold(c["path"]) == f or fold(c["path"]).endswith("> " + f))]
    if len(hits) == 1:
        return hits[0]["id"]
    if not hits:
        raise UsageError(f"no category {value!r}: find ids with `vinted categories --grep {value}`")
    raise UsageError(f"category {value!r} is ambiguous: "
                     + "; ".join(f"{c['id']} {c['path']}" for c in hits[:8]) + "; pass the id")
