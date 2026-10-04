"""list: events in a time range across calendars, recurring events expanded."""
import datetime as dt

from ...api import calendars, events, when
from ...core.errors import UsageError

FIELDS = ["start", "end", "title", "calendar", "location", "recurring", "uid"]
EPILOG = """examples:
  icloud-calendar list                                   # today + 7 days, every event calendar
  icloud-calendar list --from 2026-10-01 --to 2026-10-31 --cal Work --cal Family
  icloud-calendar list --from tomorrow --days 1 --grep dentist
  icloud-calendar list --fields start,title,uid -j

Times are shown in the zone in use (--tz, profile tz, else this machine's). All-day rows: start/end
are dates, end = last day (inclusive). A date-only --to includes that whole day.
Recurring events: one row per occurrence in range, same uid; edit/delete act on the whole series.
Subscribed (webcal) calendars are read from their public feed; reminder lists are skipped.
"""


def add_args(p):
    p.add_argument("--from", dest="start", default="today", metavar="WHEN", help="range start (default today)")
    p.add_argument("--to", dest="end", metavar="WHEN", help="range end (date = that whole day)")
    p.add_argument("--days", type=int, metavar="N", help="range length when --to is absent (default 7)")
    p.add_argument("--cal", action="append", metavar="CAL", help="calendar name or id (repeatable; default all)")
    p.add_argument("--grep", metavar="TEXT", help="only events whose title or location contains TEXT")


def _bound(s, zone, end=False):
    v, t = when.point(s, zone)
    if t is None:
        v = dt.datetime.combine(v + dt.timedelta(days=1 if end else 0), dt.time(), zone)
    return v


def run(ctx, args):
    zone = ctx.zone
    start = _bound(args.start, zone)
    if args.end:
        end = _bound(args.end, zone, end=True)
    else:
        end = start + dt.timedelta(days=args.days if args.days is not None else 7)
    if end <= start:
        raise UsageError("--to must be after --from")
    cals = [c for c in ctx.calendars() if c["events"]]
    if args.cal:
        cals = [calendars.pick(cals, s) for s in args.cal]
    rows, notes = events.list_range(ctx.session(), cals, start, end, zone)
    if args.grep:
        g = args.grep.lower()
        rows = [r for r in rows if g in r["title"].lower() or g in (r["location"] or "").lower()]
    for n in notes:
        ctx.note(n)
    if not rows:
        ctx.note(f"no events {events.show_time(start, zone)} .. {events.show_time(end, zone)}")
    ctx.write(rows, FIELDS)
