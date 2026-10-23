"""Saved searches: watch/searches.json + watch/seen/<name>.json (listings already reported, last price).
run = search again (newest first), report listings never seen (new) and numeric prices that fell (drop).
A watch stores its resolved OLX params + site at add time: no name lookups per run."""
import json
import re
import time

from ..core import paths
from ..core.errors import Broken, CliError, UsageError
from . import offers

NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
FORGET_AFTER = 60 * 86400  # a listing unseen this long is dropped from the seen file
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


def add(name, q, flags, params, site, limit):
    all_ = searches()
    name = name or slug(q or f"cat-{params.get('category_id')}")
    if not NAME.match(name):
        raise UsageError(f"bad watch name {name!r}: lowercase letters, digits, - and _")
    if name in all_:
        raise UsageError(f"watch {name!r} exists: `olx watch rm {name}` first, or pick --name")
    p = {k: v for k, v in params.items() if k != "sort_by"}
    all_[name] = {"query": q, "flags": flags, "params": p, "site": site, "limit": limit, "created": int(time.time())}
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
    f = {k: v for k, v in (w.get("flags") or {}).items() if k != "site"}
    return {"name": name, "site": w.get("site"), "query": w.get("query"),
            "flags": " ".join(f"--{k.replace('_', '-')}" + ("" if v is True else f" {v:g}" if isinstance(v, float) else f" {v}") for k, v in f.items()),
            "limit": w.get("limit"), "seen": len(_read(_seen_path(name), {})),
            "created": time.strftime("%Y-%m-%d", time.localtime(w.get("created", 0)))}


def check(name, w, now=None):
    """One saved search -> (changed rows, baseline: bool, rows looked at)."""
    now = now or int(time.time())
    params = {**(w.get("params") or {}), "sort_by": "created_at:desc"}  # newest (refreshed) first
    from .query import must_words
    rows, _, _ = offers.search(w.get("site") or "pt", params, w.get("limit") or DEFAULT_LIMIT,
                               must_words(w.get("flags") or {}))
    p = _seen_path(name)
    baseline = not p.exists()
    seen = _read(p, {})
    out = []
    for r in rows:
        key, price = str(r["id"]), r["price_value"]
        old = seen.get(key)
        if old is None:
            if not baseline:
                out.append({"watch": name, "change": "new", **r})
            seen[key] = {"title": r["title"], "price": price, "currency": r["cur"], "first": now, "last": now}
            continue
        if (price is not None and old.get("price") is not None and price < old["price"]
                and r["cur"] == old.get("currency")):
            out.append({"watch": name, "change": f"drop {offers._num(old['price'])}>{offers._num(price)}", **r})
        if price is not None:
            old.update(price=price, currency=r["cur"])
        old["last"] = now
    for k in [k for k, v in seen.items() if now - v.get("last", now) > FORGET_AFTER]:
        seen.pop(k)
    _write(p, seen)
    return out, baseline, len(rows)


def run(names, note):
    """-> (rows, failed {name: error}). A failing watch is noted, the others still run."""
    all_ = searches()
    if not all_:
        raise UsageError("no saved searches: `olx watch add \"QUERY\" [search flags]`")
    names = names or list(all_)
    missing = [n for n in names if n not in all_]
    if missing:
        raise UsageError(f"no watch {', '.join(missing)}; watches: {', '.join(all_)}")
    rows, failed = [], {}
    for n in names:
        try:
            changed, baseline, count = check(n, all_[n])
        except CliError as e:
            note(f"watch {n} failed: {e}")
            failed[n] = e
            if isinstance(e, Broken):
                for rest in names[names.index(n) + 1:]:  # a bot wall hits every watch: stop hammering
                    failed[rest] = e
                note("OLX refuses this client: remaining watches skipped")
                break
            continue
        if baseline:
            note(f"watch {n}: first run, {count} current listings recorded as baseline (not reported)")
        rows += changed
    return rows, failed
