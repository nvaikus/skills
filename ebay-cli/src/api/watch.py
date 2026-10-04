"""Saved searches: watch/searches.json + watch/seen/<name>.json (items already reported, last price).
run = search again, report items never seen (new) and fixed prices that fell (drop)."""
import json
import re
import time

from ..core import paths
from ..core.errors import CliError, UsageError
from . import browse, query

NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
FORGET_AFTER = 60 * 86400  # an item unseen this long is dropped from the seen file
DEFAULT_LIMIT = 50


def _searches_path():
    return paths.root_peek() / "watch" / "searches.json"


def _seen_path(name):
    return paths.root_peek() / "watch" / "seen" / f"{name}.json"


def _read(p, default):
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError as e:
        raise UsageError(f"{p}: invalid JSON: {e}") from None


def _write(p, data):
    paths.write_private(p, json.dumps(data, indent=1, ensure_ascii=False) + "\n")


def searches():
    return _read(_searches_path(), {})


def slug(q):
    s = re.sub(r"[^a-z0-9]+", "-", q.lower()).strip("-")[:40].strip("-")
    return s or "search"


def add(name, q, flags, limit):
    all_ = searches()
    name = name or slug(q)
    if not NAME.match(name):
        raise UsageError(f"bad watch name {name!r}: lowercase letters, digits, - and _")
    if name in all_:
        raise UsageError(f"watch {name!r} exists: `ebay watch rm {name}` first, or pick --name")
    all_[name] = {"query": q, "flags": flags, "limit": limit, "created": int(time.time())}
    _write(_searches_path(), all_)
    return name


def remove(names):
    all_ = searches()
    missing = [n for n in names if n not in all_]
    if missing:
        raise UsageError(f"no watch {', '.join(missing)}; watches: {', '.join(all_) or 'none'}")
    for n in names:
        all_.pop(n)
        try:
            _seen_path(n).unlink()
        except OSError:
            pass
    _write(_searches_path(), all_)


def describe(name, w):
    f = w.get("flags") or {}
    return {"name": name, "query": w.get("query"), "flags": " ".join(f"--{k.replace('_', '-')}"
                                                                      + ("" if v is True else f" {v}")
                                                                      for k, v in f.items()),
            "limit": w.get("limit"), "seen": len(_read(_seen_path(name), {})),
            "created": time.strftime("%Y-%m-%d", time.localtime(w.get("created", 0)))}


def check(name, w, cfg, now=None):
    """One saved search -> (changed rows, baseline: bool, total seen)."""
    now = now or int(time.time())
    flags = dict(w.get("flags") or {})
    flags.setdefault("sort", "newest")  # newest first: new listings are inside the window
    loc = query.location(flags, cfg)
    rows, _ = browse.search(query.params(w.get("query"), flags, loc, w.get("limit") or DEFAULT_LIMIT), loc)
    p = _seen_path(name)
    baseline = not p.exists()
    seen = _read(p, {})
    out = []
    for r in rows:
        key, old = r["id"] or r["item_id"], seen.get(r["id"] or r["item_id"])
        price = r["price_value"]
        if old is None:
            if not baseline:
                out.append({"watch": name, "change": "new", **r})
            seen[key] = {"title": r["title"], "price": price, "currency": r["currency"], "first": now, "last": now}
            continue
        auction = "AUCTION" in (r["buying_options"] or [])
        if (not auction and price is not None and old.get("price") is not None
                and price < old["price"] and r["currency"] == old.get("currency")):
            out.append({"watch": name, "change": f"drop {old['price']:.2f}>{price:.2f}", **r})
        old.update(price=price, currency=r["currency"], last=now)
    for k in [k for k, v in seen.items() if now - v.get("last", now) > FORGET_AFTER]:
        seen.pop(k)
    _write(p, seen)
    return out, baseline, len(rows)


def run(names, cfg, note):
    all_ = searches()
    if not all_:
        raise UsageError("no saved searches: `ebay watch add \"QUERY\" [search flags]`")
    names = names or list(all_)
    missing = [n for n in names if n not in all_]
    if missing:
        raise UsageError(f"no watch {', '.join(missing)}; watches: {', '.join(all_)}")
    rows, failed = [], []
    for n in names:
        try:
            changed, baseline, count = check(n, all_[n], cfg)
        except CliError as e:
            note(f"watch {n} failed: {e}")
            failed.append(n)
            continue
        if baseline:
            note(f"watch {n}: first run, {count} current items recorded as baseline (not reported)")
        rows += changed
    return rows, failed
