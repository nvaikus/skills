"""OLX sites + raw endpoints. The only module that knows OLX URLs."""
import re
import urllib.parse

from ..core import http
from ..core.errors import Broken, CliError, UsageError

# One API shape on every OLX Group site (verified live 2026-10-21).
SITES = {"pt": "www.olx.pt", "pl": "www.olx.pl", "ro": "www.olx.ro", "bg": "www.olx.bg", "ua": "www.olx.ua",
         "kz": "www.olx.kz", "uz": "www.olx.uz"}
PAGE = 50          # API max per call
WINDOW = 1000      # offset cap: rows past it are unreachable


def site(value):
    v = (value or "pt").lower().strip().removeprefix("www.").removeprefix("olx.")
    if v not in SITES:
        raise UsageError(f"unknown site {value!r}: one of {', '.join(SITES)}")
    return v


def base(s):
    return f"https://{SITES[s]}"


def site_of_url(url):
    host = urllib.parse.urlparse(url).netloc.lower()
    for k, h in SITES.items():
        if host == h or host.endswith("." + h.removeprefix("www.")) or host == h.removeprefix("www."):
            return k
    raise UsageError(f"not an OLX listing URL: {url!r} (sites: {', '.join(SITES.values())})")


def need(obj, keys, what):
    """Schema guard: the fields this CLI relies on. Missing -> Broken (exit 3), never a KeyError later."""
    if not isinstance(obj, dict):
        raise Broken(f"OLX schema changed: {what} is {type(obj).__name__}, not an object")
    missing = [k for k in keys if k not in obj]
    if missing:
        raise Broken(f"OLX schema changed: {what} lacks {', '.join(missing)}")
    return obj


def offers(s, params):
    body = http.get(base(s) + "/api/v1/offers/", params)
    need(body, ("data", "metadata"), "search response")
    if not isinstance(body["data"], list):
        raise Broken("OLX schema changed: search data is not a list")
    return body


def offer(s, ad_id):
    try:
        body = http.get(f"{base(s)}/api/v1/offers/{ad_id}/")
    except CliError as e:
        if e.status in (404, 410):
            raise UsageError(f"listing {ad_id} not found on {SITES[s]} (removed, expired, or another site: --site)") from None
        raise
    return need(body, ("data",), "offer response")["data"]


def id_from_page(url):
    """Listing URLs carry a short slug (…-IDJEQcI.html), not the numeric id: the page's JSON-LD has it as sku."""
    html = http.get(url, want="text")
    m = re.search(r'"sku"\s*:\s*"(\d+)"', html) or re.search(r'ad-id=(\d+)', html)
    if not m:
        raise UsageError(f"no listing id on {url} (removed listing, or not an ad page)")
    return m.group(1)


def search_categories(s, query):
    body = http.get(base(s) + "/api/v1/offers/metadata/search-categories/", {"query": query})
    data = need(body, ("data",), "search-categories response")["data"]
    return need(data, ("categories",), "search-categories data")


def home_html(s):
    return http.get(base(s) + "/", want="text")


def autocomplete(s, query):
    body = http.get(base(s) + "/api/v1/geo-encoder/location-autocomplete/", {"query": query})
    return need(body, ("data",), "location-autocomplete response")["data"]


def regions(s):
    body = http.get(base(s) + "/api/v1/geo-encoder/regions/")
    return need(body, ("data",), "regions response")["data"]
