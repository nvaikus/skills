#!/usr/bin/env python3
"""Re-record dev/tests/fixtures from live Vinted (vinted.pt): python3 dev/record_fixtures.py
Pages are cut down to the data the CLI reads, re-wrapped as one flight chunk; seller names/ids anonymized.
Re-run when Vinted changes its pages, then fix the code until the tests pass again."""
import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "dev" / "tests" / "fixtures"
os.environ.setdefault("VINTED_ROOT", tempfile.mkdtemp(prefix="vinted-rec-"))
sys.path.insert(0, str(ROOT))

from src.api import items, vinted  # noqa: E402
from src.core import http  # noqa: E402

S = "pt"
KEEP_ITEMS = 12
TREE_TOP = ("Mulher", "Homem")   # top categories kept (depth <= 3), the rest dropped
PLUGINS = ("summary", "attributes", "description", "user_info_header", "make_offer", "ask_seller")


def page(flight_obj, extra=""):
    """Minimal HTML carrying one flight chunk, the shape vinted.flight() parses."""
    text = "0:" + json.dumps(flight_obj, ensure_ascii=False, separators=(",", ":"))
    return (f"<!DOCTYPE html><html><head>{extra}</head><body>"
            f"<script>self.__next_f.push([1,{json.dumps(text)}])</script></body></html>\n")


def trim_tree_full(nodes, depth=1, maxdepth=3):
    out = []
    for n in nodes:
        if depth == 1 and n.get("title") not in TREE_TOP:
            continue
        m = {k: n.get(k) for k in ("id", "title", "url")}
        m["catalogs"] = trim_tree_full(n.get("catalogs") or [], depth + 1, maxdepth) if depth < maxdepth else []
        out.append(m)
    return out


def anon_item(it, i):
    p = it.get("productItem", it)
    if isinstance(p.get("user"), dict):
        p["user"]["id"] = 1000 + i
        for k in list(p["user"]):
            if k not in ("id", "isBusiness"):
                p["user"].pop(k)
    return it


def search_fixture():
    fl = vinted.catalog_page(S, {"search_text": "nike", "catalog[]": 1242, "size_ids[]": [776, 777, 778],
                                 "order": "newest_first"})
    its, pag = vinted.catalog_items(fl)
    tree = vinted.extract(fl, '"catalogTree":', "tree")
    dyn = vinted.extract(fl, '"dynamicFilters":{"dynamicFilters":', "filters", at=len('"dynamicFilters":'))
    its = [anon_item(it, i) for i, it in enumerate(its[:KEEP_ITEMS])]
    obj = {"items": {"items": its, "pagination": pag}, "catalogTree": trim_tree_full(tree),
           "dynamicFilters": dyn}
    (FIX / "catalog.html").write_text(page(obj), encoding="utf-8")
    return [items.row(it, S)["id"] for it in its]


def item_fixture(item_id):
    fl, html = vinted.item_page(S, item_id)
    pl = [p for p in vinted.extract(fl, '"plugins":', "plugins") if isinstance(p, dict) and p.get("name") in PLUGINS]
    for p in pl:
        d = p.get("data") or {}
        if p["name"] == "user_info_header":
            d.update(name="test_seller", id=4242, photo=None, user_info=[])
        if p["name"] == "description":
            d["description"] = "Recorded fixture. Worn a few times.\n\nShips fast, well packed."
    ps = vinted.extract(fl, '"pricingServices":', "pricing")
    cat = re.search(r'"catalog_id":"(\d+)","item_id":"' + str(item_id) + '"', fl)
    ld = vinted.ld_json(html)
    if ld:
        ld["description"] = "Recorded fixture."
    obj = {"plugins": pl, "pricingServices": ps, "ids": {"catalog_id": cat.group(1) if cat else "1242",
                                                         "item_id": str(item_id)}}
    head = f'<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>'
    text = page(obj, head)
    seller = str(next((p["data"].get("seller_id") for p in pl if p["name"] == "ask_seller"), "") or "")
    if seller:
        text = text.replace(seller, "4242")
    (FIX / "item.html").write_text(text, encoding="utf-8")


def brands_fixture():
    body = vinted.api(S, "brands", {"keyword": "nike"})
    body["brands"] = [{k: b.get(k) for k in ("id", "title", "slug", "item_count")} for b in body["brands"][:6]]
    (FIX / "brands.json").write_text(json.dumps(body, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def challenge_fixture():
    """Not fetched (it appears only when Vinted refuses): the markers of Cloudflare's challenge page."""
    (FIX / "challenge_403.html").write_text(
        "<!DOCTYPE html><html lang=\"en-US\"><head><title>Just a moment...</title></head><body>"
        "<noscript>Enable JavaScript and cookies to continue</noscript>"
        "<script>(function(){window._cf_chl_opt={cvId: '3',cZone: 'www.vinted.pt',cType: 'managed'};"
        "var a=document.createElement('script');a.src='/cdn-cgi/challenge-platform/h/g/orchestrate/chl_page/v1';"
        "}());</script></body></html>\n", encoding="utf-8")


def main():
    FIX.mkdir(parents=True, exist_ok=True)
    ids = search_fixture()
    item_fixture(ids[0])
    brands_fixture()
    challenge_fixture()
    print(f"recorded into {FIX.relative_to(ROOT)}: catalog.html ({len(ids)} items), item.html ({ids[0]}), "
          f"brands.json, challenge_403.html; health {http.health_stats()[0]}")


if __name__ == "__main__":
    main()
