"""calendars: every collection in the calendar home with kind, access and owner."""
from ...api import calendars
from ...core import config

FIELDS = ["name", "kind", "access", "owner", "comps", "color", "sharees", "default", "id"]
WRITE = True
EPILOG = """examples:
  icloud-calendar calendars
  icloud-calendar calendars --set-default Work      # where `add` goes without --cal (name or id)
  icloud-calendar calendars -j                      # + href, privileges, sharee_list, source, published

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


def run(ctx, args):
    ctx.session()
    cals = ctx.calendars()
    if args.set_default:
        cal = calendars.pick([c for c in cals if c["events"]], args.set_default)
        calendars.write_gate(cal)
        ctx.cfg = config.update(ctx.profile, default_calendar=cal["id"])
        ctx.note(f"default calendar: {cal['name']} ({cal['id']})")
    for c in cals:
        c["default"] = c["id"] == ctx.cfg.get("default_calendar")
    ctx.write(cals, FIELDS)
