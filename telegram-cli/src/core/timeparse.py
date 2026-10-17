"""--since / --until values: 7d, 12h, 30m, 2w, YYYY-MM-DD, ISO datetime. --schedule: +2h, ISO/local. Aware UTC."""
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


def parse_future(value):
    """--schedule value: +30m / +2h / +1d / +1w from now, or 'YYYY-MM-DD HH:MM' (local) / ISO with offset.
    Past or more than 365 days ahead -> UsageError (nothing sent)."""
    now = datetime.now(timezone.utc)
    m = re.fullmatch(r"\+(\d+)([mhdw])", value.strip())
    if m:
        dt = now + timedelta(**{UNITS[m.group(2)]: int(m.group(1))})
    else:
        try:
            dt = datetime.fromisoformat(value.strip())
        except ValueError:
            raise UsageError(f"bad --schedule {value!r}: use +30m / +2h / +1d, 'YYYY-MM-DD HH:MM' (local time) "
                             f"or ISO with offset - nothing sent") from None
        dt = (dt.astimezone() if dt.tzinfo is None else dt).astimezone(timezone.utc)  # naive = local time
    if dt <= now:
        raise UsageError(f"--schedule {iso(dt)} is in the past - nothing sent")
    if dt > now + timedelta(days=365):
        raise UsageError(f"--schedule {iso(dt)} is more than 365 days ahead (Telegram limit) - nothing sent")
    return dt


def iso(dt):
    return dt.astimezone().isoformat(timespec="seconds") if dt else None
