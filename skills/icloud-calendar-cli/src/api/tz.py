"""Time zones: this machine's IANA zone, TZID -> tzinfo (IANA names, prefixed names, VTIMEZONE fallback).
Windows has no system tz database: zoneinfo then needs the `tzdata` package; without it a fixed
offset of the current local time is used (DST shifts are then wrong - a note says so)."""
import datetime as dt
import os
import re
from pathlib import Path

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover - Python < 3.9
    ZoneInfo, ZoneInfoNotFoundError = None, Exception

UTC = dt.timezone.utc
_override = {"name": None}
_cache = {}


def set_default(name):
    """Profile `tz` or --tz: validated, then used by local()."""
    if name:
        zone(name)
    _override["name"] = name or None


def local_name():
    """IANA name of the zone in use: override > $TZ > /etc/localtime link > /etc/timezone > None."""
    if _override["name"]:
        return _override["name"]
    env = os.environ.get("TZ", "").lstrip(":")
    if env and _valid(env):
        return env
    try:
        target = os.path.realpath("/etc/localtime")
        m = re.search(r"zoneinfo/(.+)$", target)
        if m and _valid(m.group(1)):
            return m.group(1)
    except OSError:
        pass
    try:
        name = Path("/etc/timezone").read_text().strip()
        if _valid(name):
            return name
    except OSError:
        pass
    return None


def _valid(name):
    try:
        zone(name)
        return True
    except (KeyError, ValueError):
        return False


def zone(name):
    """IANA name -> tzinfo; KeyError when unknown."""
    if name in _cache:
        return _cache[name]
    if name.upper() in ("UTC", "Z", "GMT", "ETC/UTC"):
        _cache[name] = UTC
        return UTC
    if ZoneInfo is None:
        raise KeyError(name)
    try:
        z = ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise KeyError(name) from None
    _cache[name] = z
    return z


def local():
    name = local_name()
    if name:
        return zone(name)
    return dt.datetime.now().astimezone().tzinfo  # fixed offset: no tz database here


def resolve(tzid, cal=None):
    """TZID -> tzinfo. Tries the name, then its IANA-looking tail ('/mozilla.org/x/Europe/Lisbon'),
    then the VTIMEZONE in `cal` (fixed current offset), else the local zone."""
    tzid = (tzid or "").strip().strip('"')
    for cand in (tzid, "/".join(tzid.split("/")[-2:]), tzid.split("/")[-1]):
        if cand:
            try:
                return zone(cand)
            except KeyError:
                pass
    if cal is not None:
        for vt in cal.components("VTIMEZONE"):
            if vt.value("TZID") == tzid:
                obs = vt.components("STANDARD") or vt.subs
                if obs:
                    off = obs[-1].value("TZOFFSETTO") or "+0000"
                    m = re.fullmatch(r"([+-])(\d\d)(\d\d)", off.strip())
                    if m:
                        mins = int(m.group(2)) * 60 + int(m.group(3))
                        return dt.timezone(dt.timedelta(minutes=-mins if m.group(1) == "-" else mins), tzid)
    return local()
