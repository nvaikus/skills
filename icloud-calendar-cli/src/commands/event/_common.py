"""Flags and notes shared by add / edit / delete (module name starts with _: not a command)."""
from ...api import geo, ics, when
from ...core.stdin import text_arg

RECEIPT = ["action", "uid", "calendar", "start", "end", "title"]


def time_args(p, required=False):
    p.add_argument("--start", required=required, metavar="WHEN", help=f"start: {when.FORMS}")
    p.add_argument("--end", metavar="WHEN", help="end (timed: date-time or HH:MM; all-day: last day, inclusive)")
    p.add_argument("--duration", metavar="D", help="instead of --end: 30m, 1h30m, 2h, 1d")
    p.add_argument("--all-day", action="store_true", default=None, help="all-day event (dates only)")


def field_args(p):
    p.add_argument("--location", metavar="TEXT", help="place or address; looked up and pinned on the map "
                   "(opens Apple Maps) unless --no-geo; '' clears")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--geo", metavar="LAT,LON", help="pin the location at these coordinates (no lookup)")
    g.add_argument("--no-geo", action="store_true", help="location as plain text, no map pin (edit: drops the pin)")
    p.add_argument("--notes", metavar="TEXT", help="description; '-' reads stdin")
    p.add_argument("--url", metavar="URL")
    p.add_argument("--alarm", action="append", metavar="BEFORE",
                   help="alert before start: 10m, 1h, 1d, 0 = at start (repeatable)")
    p.add_argument("--dry-run", action="store_true", help="print the iCalendar that would be sent; change nothing")


def alarms(args):
    return [when.alarm(a) for a in args.alarm or []]


def default_alarms(cfg, start, all_day, now):
    """Profile defaults for `add` without --alarm: timed events only; triggers already past are dropped."""
    if all_day:
        return []
    today = start.date() == now.date()
    spec = cfg.get("default_alarms_today") if today and cfg.get("default_alarms_today") is not None \
        else cfg.get("default_alarms") or []
    return [a for a in map(when.alarm, spec) if start + a > now]


def place(ctx, args, text):
    """--location text -> map pin (or None), lookup notes to stderr."""
    pin, msgs = geo.resolve(text, args.geo, not args.no_geo)
    for m in msgs:
        ctx.note(m)
    return pin


def notes(args):
    return text_arg(args.notes, "--notes") if args.notes is not None else None


def kind_note(ctx, cal, action):
    if cal["kind"] == "shared-by-me":
        n = cal.get("sharees") or 0
        ctx.note(f"{cal['name']!r} is shared with {n} {'person' if n == 1 else 'people'}: they see this {action}"
                 " (iCloud may notify them)")
    elif cal["kind"] == "shared-with-me":
        ctx.note(f"{cal['name']!r} belongs to {cal['owner']}: the {action} lands in their calendar, they and other"
                 " sharees see it")


def dry(ctx, vcal):
    ctx.text(ics.to_text(vcal).replace("\r\n", "\n"))
