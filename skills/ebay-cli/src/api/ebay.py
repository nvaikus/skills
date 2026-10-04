"""Authorized eBay REST GETs (Browse, Taxonomy). Error -> the exit code a caller must act on."""
import urllib.parse

from ..core import http
from ..core.errors import CliError, UsageError
from . import auth

API = "https://api.ebay.com"
NOT_FOUND = {11001, 11002, 11003}
UNAVAILABLE = {11004, 11008}


def headers(loc):
    h = {"Authorization": f"Bearer {auth.access_token()}"}
    if loc.get("market"):
        h["X-EBAY-C-MARKETPLACE-ID"] = loc["market"]
    if loc.get("ship_to"):
        ctx = f"country={loc['ship_to']}" + (f",zip={loc['zip']}" if loc.get("zip") else "")
        h["X-EBAY-C-ENDUSERCTX"] = "contextualLocation=" + urllib.parse.quote(ctx, safe="")
    return h


def get(path, params=None, loc=None):
    loc = loc or {}
    for attempt in range(2):
        try:
            return http.request("GET", API + path, params=params, headers=headers(loc))
        except CliError as e:
            if e.status is None:  # not an HTTP answer (no keys, refused keys): already the right error
                raise
            if e.status == 401 and attempt == 0:  # token revoked or expired early: mint a fresh one once
                auth.drop()
                continue
            raise translate(e) from None


def translate(e):
    ids, msg, kw = http.error_ids(e), http.message(e.body), {"status": e.status, "body": e.body}
    if e.status == 429:
        return CliError("eBay rate limit hit (Browse allows ~5000 calls/day per app by default): wait and retry; "
                        "run `watch run` less often or with fewer searches", **kw)
    if ids & NOT_FOUND or e.status == 404:
        return UsageError(f"not found on eBay (ended, removed, or wrong market?): {msg}", **kw)
    if ids & UNAVAILABLE:
        return CliError(f"eBay says the listing is temporarily unavailable (seller editing it): retry in a few minutes - {msg}", **kw)
    if e.status == 401:
        return UsageError(f"eBay rejected the token twice: {msg} - run `ebay doctor`", **kw)
    if e.status == 403:
        return UsageError(f"eBay denied access: {msg} - the keyset may lack this API; run `ebay doctor`", **kw)
    if e.status == 400:
        return UsageError(f"eBay refused the request: {msg}", **kw)
    return CliError(f"eBay API error {e.status}: {msg}", **kw)
