"""User-facing time input: dates, date-times, relative words, durations, alarm offsets."""
import datetime as dt
import re

from ..core.errors import UsageError
from . import tz as tzmod

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
FORMS = ("YYYY-MM-DD, 'YYYY-MM-DD HH:MM', YYYY-MM-DDTHH:MM, today/tomorrow/yesterday, a weekday "
         "(mon..sun = next one, today included), each optionally followed by HH:MM; HH:MM alone = on the start day")


def today():
    return dt.datetime.now(tzmod.local()).date()


def _day_word(w):
    w = w.lower()
    t = today()
    if w == "today":
        return t
    if w == "tomorrow":
        return t + dt.timedelta(days=1)
    if w == "yesterday":
        return t - dt.timedelta(days=1)
    full = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    for i, name in enumerate(WEEKDAYS):
        if w in (name, full[i]):
            return t + dt.timedelta(days=(i - t.weekday()) % 7)
    return None


def _hm(s):
    m = re.fullmatch(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", s)
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return None
    return dt.time(int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))


def point(s, zone=None, day=None):
    """-> (date, None) for a bare date, or (aware datetime, time) for a date-time.
    `day`: the date an 'HH:MM'-only value refers to."""
    zone = zone or tzmod.local()
    raw = (s or "").strip()
    if not raw:
        raise UsageError("empty date/time")
    parts = raw.replace("T", " ", 1).split() if re.match(r"\d{4}-\d\d-\d\dT", raw) else raw.split()
    d, t = None, None
    if len(parts) in (1, 2):
        head = parts[0]
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", head):
            try:
                d = dt.date.fromisoformat(head)
            except ValueError:
                raise UsageError(f"bad date {head!r}") from None
        else:
            d = _day_word(head)
        if d is None and len(parts) == 1 and _hm(head):
            if day is None:
                raise UsageError(f"{raw!r}: a time alone needs a date ({FORMS})")
            d, t = day, _hm(head)
        elif len(parts) == 2:
            t = _hm(parts[1])
            if t is None:
                d = None
    if d is None:
        try:  # ISO with offset: 2026-10-05T14:00+01:00
            v = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return (v if v.tzinfo else v.replace(tzinfo=zone)), v.time()
        except ValueError:
            raise UsageError(f"can't read {raw!r} as a date/time; use {FORMS}") from None
    if t is None:
        return d, None
    return dt.datetime.combine(d, t, zone), t


def duration(s):
    """'90m', '1h30m', '2h', '1d', '45' (minutes) -> timedelta."""
    v = (s or "").strip().lower()
    if re.fullmatch(r"\d+", v):
        return dt.timedelta(minutes=int(v))
    m = re.fullmatch(r"(?:(\d+)d)?\s*(?:(\d+)h)?\s*(?:(\d+)m(?:in)?)?", v)
    if not v or not m or not any(m.groups()):
        raise UsageError(f"bad duration {s!r}: use e.g. 30m, 1h, 1h30m, 1d")
    d, h, mi = (int(x or 0) for x in m.groups())
    return dt.timedelta(days=d, hours=h, minutes=mi)


def alarm(s):
    """'15m' / '1h' / '1d' / '0' = before start -> negative timedelta (ICS TRIGGER)."""
    v = (s or "").strip().lstrip("-")
    if v in ("0", "0m", "at-start"):
        return dt.timedelta(0)
    return -duration(v)
