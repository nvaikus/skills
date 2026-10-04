"""edit: change fields of an existing event (the whole series when it repeats)."""
import datetime as dt

from ...api import calendars, edits, events, geo, ics, tz
from ...core.errors import UsageError
from . import _common

WRITE = True
EPILOG = """examples:
  icloud-calendar edit 6F1C2A3B --start 'fri 15:00'            # keeps the duration
  icloud-calendar edit 6F1C2A3B --title 'Dentist (moved)' --location 'Clinic B'   # new map pin too
  icloud-calendar edit 6F1C2A3B --geo 38.7029,-9.3531           # pin the current location text there
  icloud-calendar edit 6F1C2A3B --all-day                       # timed -> all-day, same day
  icloud-calendar edit 6F1C2A3B --alarm 30m --alarm 1d          # replaces every alarm; --no-alarms clears

Only the given fields change; everything else in the event (attendees, Apple-specific properties)
is kept as it is. A repeating event changes as a whole series - single occurrences are out of scope.
Fails with HTTP 412 when the event changed elsewhere since it was read: rerun.
"""


def add_args(p):
    p.add_argument("uid", help="event uid from `list`")
    p.add_argument("--title", metavar="TEXT")
    _common.time_args(p)
    p.add_argument("--timed", action="store_false", dest="all_day", default=None, help="all-day -> timed (needs --start with a time)")
    _common.field_args(p)
    p.add_argument("--no-alarms", action="store_true", help="remove every alarm")


def run(ctx, args):
    found = events.find(ctx.session(), ctx.calendars(), args.uid)
    cal, vcal = found["cal"], found["vcal"]
    calendars.write_gate(cal)
    ev = events.master_of(vcal, found["uid"])
    zone = ctx.zone
    o_start, o_all = ics.parse_value(ev.get("DTSTART"), vcal, zone)
    o_end = events._end_of(ev, o_start, o_all, vcal, zone)
    changed = []
    if any(v is not None for v in (args.start, args.end, args.duration, args.all_day)):
        start, end, all_day = edits.resolve_times(args.start, args.end, args.duration, args.all_day, zone,
                                                  old=(o_start, o_end, o_all))
        zname = ctx.zone_name
        if args.start is None and not o_all and events.zone_name_of(ev):  # only the end moves: keep its zone
            try:
                tz.zone(events.zone_name_of(ev))
                zname = events.zone_name_of(ev)
            except KeyError:
                pass
        events.set_times(ev, vcal, start, end, all_day, zname)
        ev.set("TRANSP", "TRANSPARENT" if all_day else "OPAQUE")
        changed.append("time")
    else:
        start, end, all_day = o_start, o_end, o_all
    if args.title is not None:
        ev.set_text("SUMMARY", args.title)
        changed.append("title")
    if args.location is not None:
        geo.put(ev, args.location, _common.place(ctx, args, args.location))
        changed.append("location")
    elif args.geo:
        geo.put(ev, ev.text("LOCATION"), geo.from_existing(ev, args.geo))
        changed.append("geo")
    elif args.no_geo:
        geo.clear(ev)
        changed.append("geo")
    if args.url is not None:
        ev.set("URL", args.url, {"VALUE": "URI"}) if args.url else ev.remove("URL")
        changed.append("url")
    n = _common.notes(args)
    if n is not None:
        ev.set_text("DESCRIPTION", n)
        changed.append("notes")
    if args.no_alarms or args.alarm:
        events.replace_alarms(ev, [] if args.no_alarms else _common.alarms(args), ev.text("SUMMARY"))
        changed.append("alarms")
    if not changed:
        raise UsageError("nothing to change: pass --title, --start, --end, --location, --geo, --notes, --alarm ...")
    events.touch(ev)
    if args.dry_run:
        return _common.dry(ctx, vcal)
    if ev.get("RRULE") is not None:
        ctx.note("repeating event: the change applies to the whole series")
    events.put_existing(ctx.session(), found, vcal)
    _common.kind_note(ctx, cal, "change")
    last = end - dt.timedelta(days=1) if all_day and end > start else end
    ctx.write([{"action": "edited", "uid": found["uid"], "calendar": cal["name"],
                "start": events.show_time(start, zone), "end": events.show_time(last, zone),
                "title": ev.text("SUMMARY") or "", "changed": ",".join(changed), "href": found["href"]}],
              _common.RECEIPT + ["changed"], receipt=True)
