"""delete: remove an event (the whole series when it repeats)."""
from ...api import calendars, events, ics

WRITE = True
EPILOG = """examples:
  icloud-calendar delete 6F1C2A3B
  icloud-calendar delete 6F1C2A3B --dry-run      # shows what would go

No confirmation and no trash over CalDAV: the event is gone from every device (iCloud.com keeps
deleted events restorable for 30 days under Data Recovery). A repeating event goes as a whole series.
"""


def add_args(p):
    p.add_argument("uid", help="event uid from `list`")
    p.add_argument("--dry-run", action="store_true", help="show the event that would be deleted")


def run(ctx, args):
    found = events.find(ctx.session(), ctx.calendars(), args.uid)
    cal, vcal = found["cal"], found["vcal"]
    calendars.write_gate(cal)
    ev = events.master_of(vcal, found["uid"])
    start, is_date = ics.parse_value(ev.get("DTSTART"), vcal, ctx.zone)
    row = {"action": "would delete" if args.dry_run else "deleted", "uid": found["uid"], "calendar": cal["name"],
           "start": events.show_time(start, ctx.zone), "end": None, "title": ev.text("SUMMARY") or "",
           "recurring": ev.get("RRULE") is not None, "href": found["href"]}
    if not args.dry_run:
        events.delete(ctx.session(), found)
        if row["recurring"]:
            ctx.note("repeating event: the whole series was deleted")
    ctx.write([row], ["action", "uid", "calendar", "start", "title"], receipt=True)
