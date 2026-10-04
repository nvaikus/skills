"""Five-field cron: parse, match, next occurrence, planned walk, plain words.

Semantics follow launchd, not classic cron: when BOTH day-of-month and weekday
are restricted, a time must match both (AND). Every backend registers that
meaning (systemd natively, launchd natively, Windows via a run-time re-check).
"""
import re
from datetime import datetime, timedelta

from errors import ValidationError

FIELDS = (("minute", 0, 59), ("hour", 0, 23), ("day", 1, 31), ("month", 1, 12), ("weekday", 0, 7))
DAY_NAMES = ("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")
MONTH_NAMES = ("January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December")
SCAN_DAYS = 366 * 5  # a cron like `0 0 29 2 1` (Feb 29 AND Monday) can be years away
_ITEM = re.compile(r"^(?:(\*)|(\d+)(?:-(\d+))?)(?:/(\d+))?$")


class Cron:
    """Each field is None (unrestricted) or a sorted list of ints."""

    def __init__(self, expr):
        self.expr = expr
        parts = expr.split()
        if len(parts) != 5:
            raise ValidationError(
                f"schedule needs 5 cron fields (minute hour day month weekday), got '{expr}'")
        for (name, lo, hi), spec in zip(FIELDS, parts):
            setattr(self, name, _field(spec, name, lo, hi))
        if self.weekday is not None:
            self.weekday = sorted({0 if v == 7 else v for v in self.weekday})
            if len(self.weekday) == 7:
                self.weekday = None

    def fields(self):
        return {name: getattr(self, name) for name, _, _ in FIELDS}

    def date_ok(self, dt):
        return ((self.month is None or dt.month in self.month)
                and (self.day is None or dt.day in self.day)
                and (self.weekday is None or (dt.weekday() + 1) % 7 in self.weekday))

    def hour_ok(self, dt):
        return self.hour is None or dt.hour in self.hour

    def matches(self, dt):
        return (self.date_ok(dt) and self.hour_ok(dt)
                and (self.minute is None or dt.minute in self.minute))

    def walk(self, start, end=None, limit_days=SCAN_DAYS):
        """Matching naive local minutes from `start` (inclusive), skipping whole
        days and hours that cannot match. Naive on purpose: an aware datetime keeps
        one UTC offset, so stepping across a DST change would slide 9:00 to 8:00."""
        dt = start.replace(second=0, microsecond=0)
        if dt < start:
            dt += timedelta(minutes=1)
        stop = end or (dt + timedelta(days=limit_days))
        while dt <= stop:
            if not self.date_ok(dt):
                dt = (dt + timedelta(days=1)).replace(hour=0, minute=0)
            elif not self.hour_ok(dt):
                dt = (dt + timedelta(hours=1)).replace(minute=0)
            else:
                if self.minute is None or dt.minute in self.minute:
                    yield dt
                dt += timedelta(minutes=1)

    def next_after(self, now=None):
        """Next naive-local match strictly after `now` (default: now), or None."""
        now = (now or datetime.now()).replace(second=0, microsecond=0) + timedelta(minutes=1)
        return next(self.walk(now), None)


def _field(spec, name, lo, hi):
    vals = set()
    for part in spec.split(","):
        m = _ITEM.match(part)
        if not m:
            raise ValidationError(f"cron field '{name}': cannot read '{part}'")
        star, a, b, step = m.groups()
        if star and step is None and spec == "*":
            return None
        first, last = (lo, hi) if star else (int(a), int(b) if b else int(a))
        if step is not None:
            if int(step) < 1:
                raise ValidationError(f"cron field '{name}': step must be 1 or more in '{part}'")
            if not star and b is None:
                last = hi  # `5/15` = from 5 to the end, like most crons
        if first > last:
            raise ValidationError(f"cron field '{name}': range '{part}' runs backwards")
        bad = [v for v in (first, last) if not lo <= v <= hi]
        if bad:
            raise ValidationError(f"cron field '{name}': {bad[0]} is out of range {lo}-{hi}")
        vals.update(range(first, last + 1, int(step or 1)))
    if spec != "*" and vals == set(range(lo, hi + 1)) and name != "weekday":
        return None
    return sorted(vals)


def parse(expr):
    return Cron(expr)


# ---------- plain words ----------

def _ordinal(n):
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _join(items):
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _step(vals, lo, hi):
    """N when vals is lo, lo+N, ... covering the whole field, else None."""
    if not vals or len(vals) < 2 or vals[0] != lo:
        return None
    n = vals[1] - vals[0]
    return n if vals == list(range(lo, hi + 1, n)) else None


def _span(vals):
    """'9:00–17:59' style for a contiguous hour run, else None."""
    if len(vals) > 1 and vals == list(range(vals[0], vals[-1] + 1)):
        return vals[0], vals[-1]
    return None


def _run(vals, least=3):
    """(first, last, n) when vals is an evenly stepped run (n > 1) of `least`+ values."""
    if not vals or len(vals) < least:
        return None
    n = vals[1] - vals[0]
    return (vals[0], vals[-1], n) if n > 1 and vals == list(range(vals[0], vals[-1] + 1, n)) else None


def _clock(h, m):
    return f"{h}:{m:02d}"


def _time_words(c):
    """(phrase, is_point) — is_point means 'at …' (one or a few fixed times)."""
    mins, hours = c.minute, c.hour
    one = mins is not None and len(mins) == 1
    if one and hours is not None and len(hours) > 3:  # 4+ evenly stepped hours read better as "every N hours"
        if _step(hours, 0, 23):
            tail = "" if mins[0] == 0 else f" at :{mins[0]:02d}"
            return f"every {_step(hours, 0, 23)} hours{tail}", False
        run = _run(hours) or (_span(hours) and (hours[0], hours[-1], 1))
        if run:
            each = "every hour" if run[2] == 1 else f"every {run[2]} hours"
            return f"{each} from {_clock(run[0], mins[0])} to {_clock(run[1], mins[0])}", False
    if mins is not None and hours is not None and len(mins) * len(hours) <= 6:
        return "at " + _join(_clock(h, m) for h in hours for m in mins), True
    if mins is None:
        every = "every minute"
    elif _step(mins, 0, 59):
        every = f"every {_step(mins, 0, 59)} minutes"
    elif len(mins) == 1 and hours is None:
        return ("every hour" if mins[0] == 0 else f"every hour at :{mins[0]:02d}"), False
    else:
        every = "at minute " + _join(str(m) for m in mins) + " of every hour"
    if hours is None:
        return every, False
    if mins is not None and len(mins) == 1 and _step(hours, 0, 23):
        tail = "" if mins[0] == 0 else f" at :{mins[0]:02d}"
        return f"every {_step(hours, 0, 23)} hours{tail}", False
    span = _span(hours)
    if span:
        return f"{every} from {_clock(span[0], 0)} to {_clock(span[1], 59)}", False
    return f"{every} during hours " + _join(str(h) for h in hours), False


def _weekday_words(days, lead):
    if days == [1, 2, 3, 4, 5]:
        return "every weekday" if lead else "on weekdays"
    if days == [0, 6]:
        return "every weekend day" if lead else "on weekends"
    names = [DAY_NAMES[d] for d in days]
    if len(names) == 1:
        return f"every {names[0]}" if lead else f"on {names[0]}s"
    return ("every " if lead else "on ") + _join(n[:3] for n in names)


def describe(expr):
    """Plain-English reading of a cron, for people who do not read cron.

    `0 9 * * 1-5` -> "every weekday at 9:00"; `*/15 * * * *` -> "every 15 minutes".
    An unparsable expression comes back unchanged.
    """
    try:
        c = expr if isinstance(expr, Cron) else Cron(expr)
    except ValidationError:
        return str(expr)
    when, point = _time_words(c)
    days = None
    if c.day is not None:
        days = "on the " + _join(_ordinal(d) for d in c.day) + " of " + (
            "each month" if c.month is None else _join(MONTH_NAMES[m - 1] for m in c.month))
        if c.weekday is not None:
            days += " if it is a " + _join(DAY_NAMES[d] for d in c.weekday).replace(" and ", " or ")
    elif c.weekday is not None:
        days = _weekday_words(c.weekday, lead=point)
    elif point:
        days = "every day"
    if c.month is not None and c.day is None:
        months = "in " + _join(MONTH_NAMES[m - 1] for m in c.month)
        days = f"{days} {months}" if days else months
    if not days:
        return when
    return f"{days} {when}" if point else f"{when} {days}"


# ---------- previews (web editor) ----------

def upcoming(expr, n=3, now=None):
    """Next `n` naive-local matches after `now`."""
    c = expr if isinstance(expr, Cron) else Cron(expr)
    out, at = [], now or datetime.now()
    for _ in range(n):
        at = c.next_after(at)
        if at is None:
            break
        out.append(at)
    return out


# ---------- backend helpers ----------

def oncalendar(c):
    """systemd OnCalendar= value. systemd ANDs every component, which is exactly
    the launchd semantics this tool promises."""
    def num(vals, width=2):
        return "*" if vals is None else ",".join(f"{v:0{width}d}" for v in vals)
    dow = "" if c.weekday is None else ",".join(DAY_NAMES[d][:3] for d in c.weekday) + " "
    return f"{dow}*-{num(c.month)}-{num(c.day)} {num(c.hour)}:{num(c.minute)}:00"


def calendar_intervals(c, cap=512):
    """launchd StartCalendarInterval dicts — the cartesian product of the fields."""
    keys = (("month", "Month"), ("day", "Day"), ("weekday", "Weekday"),
            ("hour", "Hour"), ("minute", "Minute"))
    out = [{}]
    for field, key in keys:
        vals = getattr(c, field)
        if vals is None:
            continue
        out = [{**d, key: v} for d in out for v in vals]
        if len(out) > cap:
            raise ValidationError(f"schedule expands to more than {cap} launchd intervals; simplify it")
    return out
