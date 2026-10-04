"""add: create an event in a calendar you can write to."""
import datetime as dt

from ...api import calendars, edits, events
from ...core.errors import UsageError
from . import _common

WRITE = True
EPILOG = """examples:
  icloud-calendar add --title 'Dentist' --start 'tomorrow 14:00' --duration 45m --alarm 1h
  icloud-calendar add --title 'Trip' --start 2026-10-10 --end 2026-10-12 --all-day --cal Family
  icloud-calendar add --title Sync --start 'mon 10:00' --end 10:30 --location 'Room 2' --no-geo --notes - < notes.txt
  icloud-calendar add --title Dinner --start 'fri 20:00' --location 'Cafe Nicola, Lisbon'   # pinned: opens Maps

Calendar: --cal (name or id) > profile default (`calendars --set-default`) > the only writable one.
Refused (exit 2) for read-only shares, subscriptions and reminder lists. In a calendar shared with
others the event is visible to them at once. Times are wall-clock in the zone in use, stored with
that zone (TZID), so Calendar shows them right wherever the user is. No --end/--duration = 1h.
--location is looked up on OpenStreetMap and pinned (Calendar shows it as a Maps link); no match or
no network = plain text + a note. --geo LAT,LON pins without lookup, --no-geo keeps plain text.
No --alarm on a timed event = profile default alerts (`profiles --set-alarms`), past ones dropped; --no-alarm = none.
"""


def add_args(p):
    p.add_argument("--title", required=True, metavar="TEXT")
    p.add_argument("--cal", metavar="CAL", help="calendar name or id")
    _common.time_args(p, required=True)
    _common.field_args(p)
    p.add_argument("--no-alarm", action="store_true", help="skip the profile's default alerts")


def run(ctx, args):
    start, end, all_day = edits.resolve_times(args.start, args.end, args.duration, args.all_day, ctx.zone)
    alarms = _common.alarms(args)
    if not alarms and not args.no_alarm:
        alarms = _common.default_alarms(ctx.cfg, start, all_day, dt.datetime.now(ctx.zone))
    if args.geo and not args.location:
        raise UsageError("--geo pins a location: pass --location TEXT too")
    place = _common.place(ctx, args, args.location)
    uid, vcal = events.new_event(args.title, start, end, all_day, ctx.zone_name, location=args.location,
                                 notes=_common.notes(args), alarms=alarms, url=args.url, place=place)
    if args.dry_run:
        return _common.dry(ctx, vcal)
    cal = calendars.choose_for_write(ctx.calendars(), args.cal, ctx.cfg)
    href, _ = events.put_new(ctx.session(), cal, uid, vcal)
    _common.kind_note(ctx, cal, "event")
    row = {"action": "added", "uid": uid, "calendar": cal["name"], "start": events.show_time(start, ctx.zone),
           "end": events.show_time(_last(end, all_day), ctx.zone), "title": args.title, "href": href,
           "all_day": all_day}
    ctx.write([row], _common.RECEIPT, receipt=True)


def _last(end, all_day):
    return end - dt.timedelta(days=1) if all_day else end
