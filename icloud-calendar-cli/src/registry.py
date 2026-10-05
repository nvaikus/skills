"""Command name -> (module, one-line help). Never import a command module here."""

AREAS = {"start": "Start here", "cal": "Calendars", "event": "Events (UID from `list`)"}
FAMILIES = set()

COMMANDS = {
    "onboard": ("src.commands.start.onboard", "guided setup of an Apple ID, one step per run (exit 5 = waiting on the user)"),
    "profiles": ("src.commands.start.profiles", "Apple IDs set up here; --default NAME; --remove NAME"),
    "calendars": ("src.commands.cal.calendars", "every calendar: name, kind, access, owner, components, color, id; --set-default, --create NAME, --delete NAME"),
    "invites": ("src.commands.cal.invites", "pending calendar share invitations (read-only; accept/decline in Calendar)"),
    "list": ("src.commands.event.list", "events in a time range, recurring ones expanded; --from --to --cal"),
    "show": ("src.commands.event.show", "one event in full: times, zone, repeat rule, alarms, notes, calendar"),
    "add": ("src.commands.event.add", "new event: --title --start [--end|--duration|--all-day] --cal --location --notes --alarm"),
    "edit": ("src.commands.event.edit", "change fields of an event (whole series when it repeats)"),
    "delete": ("src.commands.event.delete", "delete an event (whole series when it repeats)"),
}


def area(name):
    return COMMANDS[name][0].split(".")[2]
