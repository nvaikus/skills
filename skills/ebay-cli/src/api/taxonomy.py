"""Taxonomy API: category suggestions for a query (default tree of the market)."""
from . import ebay


def suggest(query, loc):
    tree = ebay.get("/commerce/taxonomy/v1/get_default_category_tree_id", {"marketplace_id": loc["market"]}, loc)
    tid = (tree or {}).get("categoryTreeId")
    r = ebay.get(f"/commerce/taxonomy/v1/category_tree/{tid}/get_category_suggestions", {"q": query}, loc) or {}
    rows = []
    for s in r.get("categorySuggestions") or []:
        c = s.get("category") or {}
        anc = sorted(s.get("categoryTreeNodeAncestors") or [], key=lambda a: a.get("categoryTreeNodeLevel", 0))
        rows.append({"id": c.get("categoryId"), "name": c.get("categoryName"),
                     "path": " > ".join([a.get("categoryName", "") for a in anc] + [c.get("categoryName", "")]),
                     "tree": tid})
    return rows
