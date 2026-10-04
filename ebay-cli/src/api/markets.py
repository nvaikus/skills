"""Marketplace facts: currency (price filter needs it) and web domain (short URLs)."""
from ..core.errors import UsageError

MARKETS = {
    "EBAY_US": ("USD", "ebay.com"), "EBAY_GB": ("GBP", "ebay.co.uk"), "EBAY_DE": ("EUR", "ebay.de"),
    "EBAY_FR": ("EUR", "ebay.fr"), "EBAY_IT": ("EUR", "ebay.it"), "EBAY_ES": ("EUR", "ebay.es"),
    "EBAY_AT": ("EUR", "ebay.at"), "EBAY_NL": ("EUR", "ebay.nl"), "EBAY_BE": ("EUR", "befr.ebay.be"),
    "EBAY_IE": ("EUR", "ebay.ie"), "EBAY_PL": ("PLN", "ebay.pl"), "EBAY_CH": ("CHF", "ebay.ch"),
    "EBAY_AU": ("AUD", "ebay.com.au"), "EBAY_CA": ("CAD", "ebay.ca"), "EBAY_HK": ("HKD", "ebay.com.hk"),
    "EBAY_SG": ("SGD", "ebay.com.sg"),
}
FALLBACK = "EBAY_US"


def norm(m):
    if not m:
        return None
    m = m.strip().upper()
    if not m.startswith("EBAY_"):
        m = "EBAY_" + ("GB" if m == "UK" else m)
    if m not in MARKETS:
        raise UsageError(f"unknown market {m!r}; one of: {', '.join(MARKETS)}")
    return m


def country(c):
    if not c:
        return None
    c = c.strip().upper()
    if c == "UK":
        c = "GB"
    if len(c) != 2 or not c.isalpha():
        raise UsageError(f"bad country {c!r}: two-letter ISO code, e.g. PT, DE, GB, US")
    return c


def currency(m):
    return MARKETS[m][0]


def item_url(m, legacy_id):
    return f"https://www.{MARKETS.get(m, MARKETS[FALLBACK])[1]}/itm/{legacy_id}".replace("www.befr.", "befr.")
