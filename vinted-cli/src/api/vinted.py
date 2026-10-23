"""Vinted sites + raw sources. The only module that knows Vinted URLs and page internals.

Search and item data come from the server-rendered pages (Next.js flight payload in
`self.__next_f.push([1,"..."])` scripts): the old JSON /api/v2/catalog/items answers 404 to web
sessions and a Cloudflare challenge without one (live-checked 2026-10-23). Brands still have JSON."""
import json
import re
import time
import urllib.parse

from ..core import http, paths
from ..core.errors import Broken, CliError, UsageError

SITES = {s: f"www.vinted.{s}" for s in (
    "pt", "fr", "es", "de", "it", "pl", "lt", "nl", "be", "at", "lu", "cz", "sk", "hu", "ro", "se", "fi", "dk",
    "gr", "hr", "ie", "co.uk")}
PAGE = 96          # rows per catalog page (fixed by Vinted; per_page is ignored)
MAX_PAGES = 10     # Vinted serves at most 10 pages (960 rows) of any search
FLIGHT = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)')
LDJSON = re.compile(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', re.S)
SESSION_TTL = 3600


def site(value):
    v = (value or "pt").lower().strip().removeprefix("https://").removeprefix("www.").removeprefix("vinted.")
    if v == "uk":
        v = "co.uk"
    if v not in SITES:
        raise UsageError(f"unknown site {value!r}: one of {', '.join(SITES)}")
    return v


def base(s):
    return f"https://{SITES[s]}"


def site_of_url(url):
    host = urllib.parse.urlparse(url).netloc.lower().removeprefix("www.")
    for k, h in SITES.items():
        if host == h.removeprefix("www."):
            return k
    raise UsageError(f"not a Vinted URL: {url!r} (sites: {', '.join(SITES.values())})")


def need(obj, keys, what):
    """Schema guard: the fields this CLI relies on. Missing -> Broken (exit 3), never a KeyError later."""
    if not isinstance(obj, dict):
        raise Broken(f"Vinted page data changed: {what} is {type(obj).__name__}, not an object")
    missing = [k for k in keys if k not in obj]
    if missing:
        raise Broken(f"Vinted page data changed: {what} lacks {', '.join(missing)}")
    return obj


def flight(html):
    """The page's Next.js flight payload as one string (React Server Component rows)."""
    chunks = FLIGHT.findall(html)
    if not chunks:
        if http.challenged(html):
            raise Broken("Vinted answered a Cloudflare challenge page; see references/traps.md 'When it breaks'")
        raise Broken("Vinted page changed: no Next.js flight data (self.__next_f) in the HTML")
    try:
        return "".join(json.loads(c) for c in chunks)
    except ValueError as e:
        raise Broken(f"Vinted page changed: flight data unreadable ({e})") from None


def extract(fl, key, what, default=None, at=None):
    """JSON value right after `key` (e.g. '"catalogTree":') in the flight text, or `at` chars into the match
    when the key includes the value's start; Broken if absent and no default."""
    i = fl.find(key)
    if i < 0:
        if default is not None:
            return default
        raise Broken(f"Vinted page changed: no {what} ({key.rstrip(':')}) in the page data")
    try:
        return json.JSONDecoder().raw_decode(fl, i + (len(key) if at is None else at))[0]
    except ValueError as e:
        raise Broken(f"Vinted page changed: {what} unreadable ({e})") from None


def catalog_page(s, params):
    """-> flight text of /catalog?<params> (one page of 96 rows + filters + category tree)."""
    return flight(http.get(base(s) + "/catalog", params, want="text"))


def catalog_items(fl):
    """-> (items, pagination) from a catalog page's flight."""
    box = need(extract(fl, '"items":{"items":[', "search results", at=len('"items":')),
               ("items", "pagination"), "search results")
    if not isinstance(box["items"], list):
        raise Broken("Vinted page data changed: search items is not a list")
    return box["items"], box.get("pagination") or {}


def item_page(s, item_id):
    """-> (flight text, raw HTML) of /items/<id> (Vinted redirects to the slug URL)."""
    try:
        html = http.get(f"{base(s)}/items/{item_id}", want="text")
    except CliError as e:
        if e.status in (404, 410):
            raise UsageError(f"item {item_id} not found on {SITES[s]} (sold and removed, hidden, or another "
                             "site: --site)") from None
        raise
    return flight(html), html


def ld_json(html):
    """schema.org Product block of an item page, or {}."""
    for block in LDJSON.findall(html):
        try:
            d = json.loads(block)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("@type") == "Product":
            return d
    return {}


# --- JSON API (brands): needs the anonymous session cookie the home page sets --------------------------------

def _session_path(s):
    return paths.root_peek() / f"session-{s.replace('.', '-')}.json"


def session(s, refresh=False):
    """-> Cookie header value. Cached per site for SESSION_TTL; refresh=True fetches the home page again."""
    p = _session_path(s)
    if not refresh and p.exists():
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            if time.time() - d.get("at", 0) < SESSION_TTL and d.get("cookie"):
                return d["cookie"]
        except ValueError:
            pass
    jar = http.get(base(s) + "/", want="cookies")
    if "access_token_web" not in jar:
        http.health(SITES[s], "/", "schema", "no access_token_web cookie")
        raise Broken(f"Vinted home page set no access_token_web cookie on {SITES[s]}: the anonymous session flow "
                     "changed; see references/traps.md 'When it breaks'")
    cookie = "; ".join(f"{k}={v}" for k, v in jar.items())
    paths.write_private(p, json.dumps({"at": int(time.time()), "cookie": cookie}))
    return cookie


def api(s, path, params=None):
    """GET /api/v2/<path> with the session cookie; one cookie refresh on 401."""
    for attempt in (0, 1):
        try:
            return http.get(f"{base(s)}/api/v2/{path}", params, headers={"Cookie": session(s, attempt == 1)})
        except CliError as e:
            if e.status == 401 and attempt == 0:
                continue
            raise


def brands(s, keyword):
    body = api(s, "brands", {"keyword": keyword})
    lst = need(body, ("brands",), "brands response")["brands"]
    if not isinstance(lst, list):
        raise Broken("Vinted API changed: brands is not a list")
    return lst
