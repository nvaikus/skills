"""show: one event in full."""
import datetime as dt

from ...api import events, geo, ics

EPILOG = """examples:
  icloud-calendar show 6F1C2A3B-...            # uid from `list` (a unique leading part of 6+ chars works)
  icloud-calendar show 6F1C2A3B -j             # fields + raw ICS under "ics"
"""


def add_args(p):
    p.add_argument("uid", help="event uid from `list`")


def _alarm(a):
    trig = a.value("TRIGGER") or ""
    try:
        td = -ics.parse_duration(trig)
    except ValueError:
        return trig
    if td == dt.timedelta(0):
        return "at start"
    mins = int(td.total_seconds() // 60)
    for unit, n in (("d", 1440), ("h", 60)):
        if mins % n == 0 and mins >= n:
            return f"{mins // n}{unit} before"
    return f"{mins}m before" if mins >= 0 else f"{-mins}m after"


def run(ctx, args):
    found = events.find(ctx.session(), ctx.calendars(), args.uid)
    vcal, cal, zone = found["vcal"], found["cal"], ctx.zone
    ev = events.master_of(vcal, found["uid"])
    start, is_date = ics.parse_value(ev.get("DTSTART"), vcal, zone)
    end = events._end_of(ev, start, is_date, vcal, zone)
    shown_end = end - dt.timedelta(days=1) if is_date and end > start else end
    overrides = [e for e in vcal.components("VEVENT") if e.get("RECURRENCE-ID") is not None]
    meta = {"uid": found["uid"], "title": ev.text("SUMMARY") or "", "start": events.show_time(start, zone),
            "end": events.show_time(shown_end, zone), "all_day": is_date,
            "event_tz": ev.get("DTSTART").params.get("TZID"), "location": ev.text("LOCATION"),
            "notes": ev.text("DESCRIPTION"), "url": ev.value("URL"), "repeat": ev.value("RRULE"),
            "exceptions": len(ev.all("EXDATE")) + len(overrides),
            "alarms": [_alarm(a) for a in ev.components("VALARM")], "status": ev.value("STATUS"),
            "calendar": cal["name"], "kind": cal["kind"], "access": cal["access"], "href": found["href"],
            "etag": found["etag"]}
    pin = geo.read(ev)
    meta["geo"], meta["maps_url"] = (f"{pin['lat']},{pin['lon']}", pin["maps_url"]) if pin else (None, None)
    lines = [f"# {meta['title'] or '(no title)'}", "",
             f"- when: {meta['start']} - {meta['end']}" + (" (all day)" if is_date else f" ({ctx.zone_name})")]
    if meta["event_tz"] and not is_date and meta["event_tz"] != ctx.zone_name:
        lines.append(f"- event zone: {meta['event_tz']}")
    lines.append(f"- calendar: {cal['name']} ({cal['kind']}, {cal['access']})")
    for k in ("location", "url", "repeat", "status"):
        if meta[k]:
            lines.append(f"- {k}: {meta[k]}".replace("\n", ", "))
        if k == "location" and pin:
            lines.append(f"- map: {meta['geo']} {meta['maps_url']}")
    if meta["exceptions"]:
        lines.append(f"- changed/removed occurrences: {meta['exceptions']}")
    if meta["alarms"]:
        lines.append(f"- alarms: {', '.join(meta['alarms'])}")
    lines.append(f"- uid: {found['uid']}")
    if meta["notes"]:
        lines += ["", meta["notes"]]
    if ctx.args.json:
        meta["ics"] = found["ics"]
    ctx.text("\n".join(lines), meta)
