"""--since / --until values: 7d, 12h, 30m, 2w, YYYY-MM-DD, ISO datetime. Returns aware UTC."""
import re
from datetime import datetime, timedelta, timezone

from .errors import UsageError

UNITS = {"m": "minutes", "h": "hours", "d": "days", "w": "weeks"}


def parse_when(value):
    if value is None:
        return None
    m = re.fullmatch(r"(\d+)([mhdw])", value.strip())
    if m:
        return datetime.now(timezone.utc) - timedelta(**{UNITS[m.group(2)]: int(m.group(1))})
    try:
        dt = datetime.fromisoformat(value.strip())
    except ValueError:
        raise UsageError(f"bad time {value!r}: use 7d / 12h / 30m / 2w, YYYY-MM-DD or ISO datetime") from None
    if dt.tzinfo is None:
        dt = dt.astimezone()  # naive = local time
    return dt.astimezone(timezone.utc)


def iso(dt):
    return dt.astimezone().isoformat(timespec="seconds") if dt else None
