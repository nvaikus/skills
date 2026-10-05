"""calendars: every collection in the calendar home with kind, access and owner."""
from ...api import calendars
from ...core import config
from ...core.errors import UsageError

FIELDS = ["name", "kind", "access", "owner", "comps", "color", "sharees", "default", "id"]
WRITE = True
EPILOG = """examples:
  icloud-calendar calendars
  icloud-calendar calendars --set-default Work      # where `add` goes without --cal (name or id)
  icloud-calendar calendars -j                      # + href, privileges, sharee_list, source, published
  icloud-calendar calendars --create Gym --color '#34C759'   # new own calendar (events), prints its row
  icloud-calendar calendars --delete Gym            # own only; exact name or id; non-empty needs --force

kind (how writes behave):
  own             yours, not shared                          add/edit/delete
  shared-by-me    yours, shared (sharees column = people)    add/edit/delete; sharees see it, may be notified
  shared-with-me  someone else's; owner = who shared it      access rw: writes land in the owner's calendar
                                                             access ro: add/edit/delete refused
  subscribed      webcal feed (holidays, sports...)          read-only; `list` reads the public feed
  reminders       VTODO list                                 not shown by event commands
"""


def add_args(p):
    p.add_argument("--set-default", metavar="CAL", help="calendar name or id used by `add` without --cal")
    p.add_argument("--create", metavar="NAME", help="create an own event calendar (same name exists -> exit 2)")
    p.add_argument("--color", metavar="#RRGGBB", help="with --create: calendar color")
    p.add_argument("--delete", metavar="CAL", help="delete an own calendar (exact name or id)")
    p.add_argument("--force", action="store_true", help="with --delete: delete even when it holds events")


def run(ctx, args):
    if sum(bool(x) for x in (args.set_default, args.create, args.delete)) > 1:
        raise UsageError("one of --set-default / --create / --delete at a time")
    if args.color and not args.create:
        raise UsageError("--color goes with --create")
    if args.force and not args.delete:
        raise UsageError("--force goes with --delete")
    session = ctx.session()
    cals = ctx.calendars()
    if args.create:
        cal = calendars.create(session, ctx.cfg, cals, args.create, args.color)
        cal["default"] = False
        ctx.note(f"created {cal['name']!r} ({cal['id']}); syncs to every device")
        return ctx.write([cal], FIELDS)
    if args.delete:
        cal, n = calendars.remove(session, cals, args.delete, args.force)
        ctx.note(f"deleted {cal['name']!r} ({cal['id']})" + (f" with {n} event(s)" if n else ""))
        if ctx.cfg.get("default_calendar") == cal["id"]:
            ctx.cfg = config.update(ctx.profile, default_calendar=None)
            ctx.note("it was the default calendar: default cleared")
        return ctx.write([{"action": "deleted", "name": cal["name"], "events": n, "id": cal["id"]}],
                         ["action", "name", "events", "id"], receipt=True)
    if args.set_default:
        cal = calendars.pick([c for c in cals if c["events"]], args.set_default)
        calendars.write_gate(cal)
        ctx.cfg = config.update(ctx.profile, default_calendar=cal["id"])
        ctx.note(f"default calendar: {cal['name']} ({cal['id']})")
    for c in cals:
        c["default"] = c["id"] == ctx.cfg.get("default_calendar")
    ctx.write(cals, FIELDS)
