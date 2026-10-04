"""Turn add/edit flags into start/end values; shared by `add` and `edit`."""
import datetime as dt

from ..core.errors import UsageError
from . import when


def resolve_times(start_s, end_s, duration_s, all_day, zone, old=None):
    """-> (start, end_exclusive, all_day). old = (start, end, all_day) of the event being edited."""
    if old and start_s is None:
        o_start, o_end, o_all = old
        if all_day is None or all_day == o_all:
            start = o_start
            all_day = o_all
        elif all_day:  # timed -> all-day, same day
            start = o_start.astimezone(zone).date() if isinstance(o_start, dt.datetime) else o_start
        else:
            raise UsageError("--timed needs --start with a time")
    else:
        if start_s is None:
            raise UsageError("--start is required")
        start, t = when.point(start_s, zone)
        if all_day is None:
            all_day = t is None and old is not None and old[2]
            if t is None and not all_day:
                raise UsageError(f"--start {start_s!r} has no time: add one (e.g. '{start_s} 14:00') or pass --all-day")
        if all_day and isinstance(start, dt.datetime):
            start = start.date()
    if all_day:
        if end_s:
            end, _ = when.point(end_s, zone, day=start)
            end = end.date() if isinstance(end, dt.datetime) else end
            if end < start:
                raise UsageError("--end is before --start")
            return start, end + dt.timedelta(days=1), True
        if duration_s:
            days = max(1, when.duration(duration_s).days)
            return start, start + dt.timedelta(days=days), True
        if old and start_s is None and old[2]:
            return start, old[1], True
        if old and old[2]:
            return start, start + (old[1] - old[0]), True
        return start, start + dt.timedelta(days=1), True
    if end_s:
        end, t = when.point(end_s, zone, day=start.astimezone(zone).date())
        if t is None:
            raise UsageError(f"--end {end_s!r} has no time")
    elif duration_s:
        end = start + when.duration(duration_s)
    elif old and not old[2]:
        end = start + (old[1] - old[0])
    else:
        end = start + dt.timedelta(hours=1)
    if end <= start:
        raise UsageError("--end must be after --start")
    return start, end, False
