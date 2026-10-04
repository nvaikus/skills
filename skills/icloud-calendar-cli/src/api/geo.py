"""Map pins for LOCATION: geocode the text (OpenStreetMap Nominatim, Photon as fuzzy fallback) and write
Apple's X-APPLE-STRUCTURED-LOCATION + standard GEO, so Calendar shows a location that opens Maps.
Geocoding never fails a write: no hit or no network = plain LOCATION + a note."""
import json
import math
import re
import unicodedata
import urllib.parse

from ..core import http
from ..core.errors import CliError, UsageError

NOMINATIM = "https://nominatim.openstreetmap.org/search"
PHOTON = "https://photon.komoot.io/api/"
UA = "icloud-calendar/1.0 (+https://github.com/nvaikus/skills)"  # Nominatim policy: identify the app
TIMEOUT = 6
DEFAULT_RADIUS = 70  # metres; what Calendar writes for a street address
STRUCT = "X-APPLE-STRUCTURED-LOCATION"


# ---------- text split (Apple: X-TITLE = name line, X-ADDRESS = the rest)

def split(text):
    """'Name\\nStreet, City' or 'Name, Street, City' -> ('Name', 'Street, City')."""
    t = (text or "").strip()
    if "\n" in t:
        head, rest = t.split("\n", 1)
        return head.strip(), ", ".join(x.strip() for x in rest.split("\n") if x.strip())
    head, _, rest = t.partition(",")
    return head.strip(), rest.strip()


def _fold(s):
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).casefold()


def _complete(title, rest, parts):
    """User's remainder + geocoder parts (locality, country) it does not mention yet."""
    seen = _fold(title + " " + rest)
    out = [rest] if rest else []
    for p in parts:
        if p and _fold(p) not in seen:
            out.append(p)
            seen += " " + _fold(p)
    return ", ".join(out)


def _clean(name):
    return re.sub(r"\s*\(.*?\)\s*$", "", name or "").strip()  # 'Sintra (Santa Maria e ...)' -> 'Sintra'


# ---------- coordinates

def parse_coords(s):
    m = re.fullmatch(r"\s*([+-]?\d+(?:\.\d+)?)\s*[,; ]\s*([+-]?\d+(?:\.\d+)?)\s*", s or "")
    if not m:
        raise UsageError(f"--geo {s!r}: expected LAT,LON in decimal degrees, e.g. 38.7029,-9.3531")
    lat, lon = float(m.group(1)), float(m.group(2))
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise UsageError(f"--geo {s!r}: latitude must be -90..90 and longitude -180..180")
    return lat, lon


def _radius(lat, s, n, w, e):
    dy = (n - s) * 111320 / 2
    dx = (e - w) * 111320 * math.cos(math.radians(lat)) / 2
    return int(min(max(math.hypot(dx, dy), 50), 1000))


# ---------- lookup

def _get(url, params):
    r = http.request("GET", url + "?" + urllib.parse.urlencode(params), headers={"User-Agent": UA,
                     "Accept": "application/json"}, timeout=TIMEOUT, retries=0, ok=(200,))
    return json.loads(r.text)


def _nominatim(q):
    data = _get(NOMINATIM, {"format": "jsonv2", "addressdetails": 1, "limit": 1, "q": q})
    if not data:
        return None
    h = data[0]
    a = h.get("address") or {}
    lat, lon = float(h["lat"]), float(h["lon"])
    locality = next((_clean(a[k]) for k in ("village", "town", "city", "municipality", "hamlet", "suburb")
                     if a.get(k)), "")
    try:
        s, n, w, e = map(float, h["boundingbox"])
        radius = _radius(lat, s, n, w, e)
    except (KeyError, TypeError, ValueError):
        radius = DEFAULT_RADIUS
    return {"lat": lat, "lon": lon, "radius": radius, "parts": [locality, a.get("country", "")],
            "matched": h.get("display_name", ""), "source": "OpenStreetMap"}


def _photon(q, rest):
    data = _get(PHOTON, {"q": q, "limit": 1})
    feats = data.get("features") or []
    if not feats:
        return None
    p, (lon, lat) = feats[0].get("properties") or {}, feats[0]["geometry"]["coordinates"][:2]
    fields = [p.get(k) or "" for k in ("name", "street", "housenumber", "locality", "district", "city", "county",
                                       "state", "postcode", "country")]
    words = re.findall(r"\w{4,}", _fold(rest))
    if words and not any(w in _fold(" ".join(fields)) for w in words):
        return None  # fuzzy hit elsewhere: none of the user's place words match
    try:
        w, n, e, s = map(float, p["extent"])
        radius = _radius(lat, s, n, w, e)
    except (KeyError, TypeError, ValueError):
        radius = DEFAULT_RADIUS
    locality = _clean(p.get("city") or p.get("locality") or p.get("district") or "")
    matched = ", ".join(x for x in (p.get("name"), p.get("housenumber"), locality, p.get("country")) if x)
    return {"lat": float(lat), "lon": float(lon), "radius": radius, "parts": [locality, p.get("country", "")],
            "matched": matched, "source": "Photon (fuzzy)"}


def lookup(text):
    """-> (hit | None, reason). Nominatim first (exact); Photon when Nominatim has no hit (typos, extra words)."""
    title, rest = split(text)
    q = ", ".join(x for x in (title, rest) if x)
    try:
        hit = _nominatim(q) or _photon(q, rest)
    except (CliError, ValueError, KeyError, TypeError, IndexError) as e:
        return None, f"geocoder unreachable ({e})"
    return hit, None if hit else "no map match"


# ---------- resolve + write

def resolve(text, coords=None, enabled=True):
    """--location text (+ --geo / --no-geo) -> (place | None, notes). place = what `put` writes."""
    if not text or not text.strip() or not enabled:
        return None, []
    title, rest = split(text)
    if coords:
        lat, lon = parse_coords(coords)
        return {"lat": lat, "lon": lon, "radius": DEFAULT_RADIUS, "title": title, "address": rest,
                "location": text}, []
    hit, why = lookup(text)
    if not hit:
        return None, [f"location {text!r}: {why}; saved as plain text without a map pin "
                      "(pass --geo LAT,LON to pin it)"]
    address = _complete(title, rest, hit["parts"])
    place = {"lat": hit["lat"], "lon": hit["lon"], "radius": hit["radius"], "title": title, "address": address,
             "location": title + ("\n" + address if address else "")}
    return place, [f"location pinned at {_ll(place)} via {hit['source']}: {hit['matched']} - wrong place? "
                   "pass --geo LAT,LON or --no-geo"]


def _ll(place):
    return f"{place['lat']:.6f},{place['lon']:.6f}"


def _param(v):
    """Param values may not hold DQUOTE or control characters (RFC 5545 3.1); ':;,' get quoted by ics."""
    v = re.sub(r"[\r\n]+", ", ", v or "")
    return re.sub(r"[\x00-\x1f\x7f]", " ", v.replace('"', "'")).strip()


def put(ev, text, place):
    """LOCATION (+ X-APPLE-STRUCTURED-LOCATION and GEO when place)."""
    if not place:
        ev.set_text("LOCATION", text)
        clear(ev)
        return
    ev.set_text("LOCATION", place["location"])
    params = {"VALUE": "URI"}
    if place["address"]:
        params["X-ADDRESS"] = _param(place["address"])
    params.update({"X-APPLE-RADIUS": str(place["radius"]), "X-APPLE-REFERENCEFRAME": "1",
                   "X-TITLE": _param(place["title"]) or _ll(place)})
    ev.set(STRUCT, "geo:" + _ll(place), params)
    ev.set("GEO", f"{place['lat']:.6f};{place['lon']:.6f}")


def clear(ev):
    ev.remove(STRUCT)
    ev.remove("GEO")


def read(ev):
    """-> {lat, lon, maps_url} from the structured location (or GEO), else None."""
    p = ev.get(STRUCT)
    m = re.match(r"geo:([+-]?[\d.]+),([+-]?[\d.]+)", p.value.strip(), re.I) if p is not None else None
    title = p.params.get("X-TITLE") if p is not None else None
    if not m and ev.value("GEO"):
        m = re.fullmatch(r"\s*([+-]?[\d.]+)\s*[;,]\s*([+-]?[\d.]+)\s*", ev.value("GEO"))
    if not m:
        return None
    lat, lon = m.group(1), m.group(2)
    title = title or split(ev.text("LOCATION") or "")[0] or f"{lat},{lon}"
    return {"lat": float(lat), "lon": float(lon),
            "maps_url": f"https://maps.apple.com/?ll={lat},{lon}&q={urllib.parse.quote(title)}"}


def from_existing(ev, coords):
    """edit --geo without --location: pin the event's current LOCATION text."""
    text = ev.text("LOCATION")
    if not text:
        raise UsageError("--geo needs a location: pass --location TEXT too (the event has none)")
    return resolve(text, coords)[0]

