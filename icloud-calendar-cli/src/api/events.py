"""Events: range listing (server expand, local RRULE fallback), lookup by UID, build and change
VEVENTs, PUT/DELETE with ETag preconditions."""
import datetime as dt
import uuid
from concurrent.futures import ThreadPoolExecutor
from xml.sax.saxutils import escape as xesc

from ..core import http
from ..core.errors import CliError, UsageError
from . import geo, ics, recur
from . import tz as tzmod

UTC = dt.timezone.utc
PRODID = "-//icloud-calendar//CalDAV CLI//EN"


# ---------- time helpers

def as_utc(t, zone):
    """date -> local midnight in zone; datetime -> UTC."""
    if isinstance(t, dt.datetime):
        return t.astimezone(UTC)
    return dt.datetime.combine(t, dt.time(), zone).astimezone(UTC)


def show_time(t, zone):
    if isinstance(t, dt.datetime):
        return t.astimezone(zone).strftime("%Y-%m-%d %H:%M")
    return t.isoformat()


def _end_of(ev, start, is_date, cal, zone):
    p = ev.get("DTEND")
    if p is not None:
        return ics.parse_value(p, cal, zone)[0]
    d = ev.value("DURATION")
    if d:
        return start + ics.parse_duration(d)
    return start + dt.timedelta(days=1) if is_date else start


# ---------- instances

def instances(vcal, rng_start, rng_end, zone, expanded_by=None):
    """VCALENDAR -> instance dicts overlapping [rng_start, rng_end) (UTC datetimes).
    A recurring master is expanded locally; RECURRENCE-ID overrides replace their occurrence."""
    out, notes = [], []
    by_uid = {}
    for ev in vcal.components("VEVENT"):
        by_uid.setdefault(ev.value("UID", ""), []).append(ev)
    for uid, evs in by_uid.items():
        masters = [e for e in evs if e.get("RECURRENCE-ID") is None]
        overrides = [e for e in evs if e.get("RECURRENCE-ID") is not None]
        master = masters[0] if masters else None
        series = bool(master is not None and master.get("RRULE")) or bool(overrides)
        override_keys = set()
        for o in overrides:
            rid = ics.parse_value(o.get("RECURRENCE-ID"), vcal, zone)[0]
            override_keys.add(recur._key(rid))
            inst = _instance(o, vcal, zone, rid, series, expanded_by or "server")
            if inst and _overlaps(inst, rng_start, rng_end, zone):
                out.append(inst)
        if master is None:
            continue
        start, is_date = ics.parse_value(master.get("DTSTART"), vcal, zone)
        if master.get("RRULE") is None:
            inst = _instance(master, vcal, zone, None, series, expanded_by)
            if inst and _overlaps(inst, rng_start, rng_end, zone):
                out.append(inst)
            continue
        end = _end_of(master, start, is_date, vcal, zone)
        length = end - start
        ex = [x for p in master.all("EXDATE") for x in ics.list_values(p, vcal, zone)]
        rd = [x for p in master.all("RDATE") for x in ics.list_values(p, vcal, zone)]
        limit = rng_end.astimezone(zone).date() + dt.timedelta(days=1) if is_date else rng_end
        try:
            starts = recur.occurrences(start, master.value("RRULE"), limit, extra=rd, exdates=ex)
        except (recur.Unsupported, ValueError) as e:
            notes.append(f"{master.text('SUMMARY') or uid}: repeat rule not expanded here ({e}); first occurrence only")
            starts = [start]
        for s in starts:
            if recur._key(s) in override_keys:
                continue
            inst = _instance(master, vcal, zone, s, True, "local", start_over=(s, s + length))
            if inst and _overlaps(inst, rng_start, rng_end, zone):
                out.append(inst)
    return out, notes


def _instance(ev, vcal, zone, rid, recurring, expanded_by, start_over=None):
    if ev.get("DTSTART") is None:
        return None
    if start_over:
        start, end = start_over
        is_date = not isinstance(start, dt.datetime)
    else:
        start, is_date = ics.parse_value(ev.get("DTSTART"), vcal, zone)
        end = _end_of(ev, start, is_date, vcal, zone)
    return {"uid": ev.value("UID"), "title": ev.text("SUMMARY") or "", "start_v": start, "end_v": end,
            "all_day": is_date, "location": ev.text("LOCATION") or "", "recurring": recurring,
            "recurrence_id": show_time(rid, zone) if rid is not None else None,
            "status": ev.value("STATUS"), "expanded": expanded_by}


def _overlaps(inst, s, e, zone):
    a, b = as_utc(inst["start_v"], zone), as_utc(inst["end_v"], zone)
    if b <= a:
        return s <= a < e
    return a < e and b > s


def row(inst, cal, zone):
    end = inst["end_v"]
    if inst["all_day"]:
        end = end - dt.timedelta(days=1) if end > inst["start_v"] else end  # inclusive last day
    return {"start": show_time(inst["start_v"], zone), "end": show_time(end, zone), "all_day": inst["all_day"],
            "title": inst["title"], "calendar": cal["name"], "location": inst["location"],
            "recurring": inst["recurring"], "uid": inst["uid"], "recurrence_id": inst["recurrence_id"],
            "status": inst["status"], "cal_id": cal["id"], "kind": cal["kind"], "expanded": inst["expanded"],
            "_sort": as_utc(inst["start_v"], zone)}


# ---------- fetch

def _zstamp(t):
    return t.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def query_range(session, cal, start, end, zone):
    """-> (instances, notes) for one CalDAV calendar. Asks the server to expand recurrences; any master
    that comes back with its RRULE (server did not expand) is expanded locally."""
    tr = f'start="{_zstamp(start)}" end="{_zstamp(end)}"'
    inner = (f'<d:prop><d:getetag/><c:calendar-data><c:expand {tr}/></c:calendar-data></d:prop>'
             f'<c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VEVENT">'
             f'<c:time-range {tr}/></c:comp-filter></c:comp-filter></c:filter>')
    items = session.report(cal["href"], "C:calendar-query", inner, depth=1)
    out, notes = [], []
    for it in items:
        data = it.text("C:calendar-data")
        if not data:
            continue
        try:
            vcal = ics.parse(data)
        except ValueError as e:
            notes.append(f"{it.href}: unparseable event skipped ({e})")
            continue
        unexpanded = any(e.get("RRULE") is not None for e in vcal.components("VEVENT"))
        insts, n = instances(vcal, start, end, zone, expanded_by=None if unexpanded else "server")
        out += insts
        notes += n
    return out, notes


def feed_range(cal, start, end, zone):
    """Subscribed calendar: GET its public feed (webcal -> https), expand locally."""
    src = cal.get("source") or ""
    if src.startswith("webcal://"):
        src = "https://" + src[len("webcal://"):]
    if not src.startswith(("http://", "https://")):
        return [], [f"{cal['name']}: subscription has no fetchable source URL"]
    r = http.request("GET", src, headers={"Accept": "text/calendar"}, ok=(200,))
    return instances(ics.parse(r.text), start, end, zone, expanded_by="local")


def list_range(session, cals, start, end, zone):
    """-> (rows sorted by start, notes). Calendars are queried in parallel."""
    def one(cal):
        try:
            if cal["kind"] == "subscribed":
                insts, notes = feed_range(cal, start, end, zone)
            else:
                insts, notes = query_range(session, cal, start, end, zone)
            return [row(i, cal, zone) for i in insts], notes
        except CliError as e:
            if cal["kind"] != "subscribed":
                raise  # a public feed failing (even 401) never aborts the whole listing
            return [], [f"{cal['name']}: feed not readable ({e})"]
    rows, notes = [], []
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(cals)))) as ex:
        for r, n in ex.map(one, cals):
            rows += r
            notes += n
    rows.sort(key=lambda r: (r["_sort"], r["title"]))
    for r in rows:
        r.pop("_sort", None)
    return rows, notes


# ---------- lookup by UID

def _uid_query(uid):
    return ('<d:prop><d:getetag/><c:calendar-data/></d:prop>'
            '<c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VEVENT">'
            f'<c:prop-filter name="UID"><c:text-match collation="i;octet">{xesc(uid)}</c:text-match>'
            '</c:prop-filter></c:comp-filter></c:comp-filter></c:filter>')


def find(session, cals, uid):
    """UID (or a unique prefix of one) -> {cal, href, etag, ics, vcal, uid}. Searches every CalDAV
    event calendar given, in parallel; exit 2 when missing or ambiguous."""
    uid = uid.strip()
    if len(uid) < 6:
        raise UsageError("uid too short: pass the full uid (or at least 6 leading characters) from `list`")

    def one(cal):
        try:
            items = session.report(cal["href"], "C:calendar-query", _uid_query(uid), depth=1)
        except CliError as e:
            if e.status in (401, 0):
                raise
            try:  # server refused the text-match: try the conventional resource name
                r = session.get(cal["href"] + uid + ".ics")
                return [(cal, r.url, r.header("ETag"), r.text)]
            except CliError:
                return []
        return [(cal, it.href, it.text("D:getetag"), it.text("C:calendar-data")) for it in items
                if it.text("C:calendar-data")]
    found = []
    targets = [c for c in cals if c["events"] and c["kind"] != "subscribed"]
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(targets)))) as ex:
        for hits in ex.map(one, targets):
            for cal, href, etag, data in hits:
                vcal = ics.parse(data)
                uids = {e.value("UID") for e in vcal.components("VEVENT")}
                for u in uids:
                    if u == uid or (u or "").startswith(uid):
                        found.append({"cal": cal, "href": href, "etag": etag, "ics": data, "vcal": vcal, "uid": u})
    exact = [f for f in found if f["uid"] == uid]
    found = exact or found
    if not found:
        raise UsageError(f"no event with uid {uid!r} in your CalDAV calendars (subscribed feeds are not searched)")
    if len({(f["uid"], f["href"]) for f in found}) > 1:
        raise UsageError(f"uid {uid!r} matches several events: pass the full uid",
                         payload=[{"uid": f["uid"], "calendar": f["cal"]["name"]} for f in found])
    return found[0]


def master_of(vcal, uid):
    evs = [e for e in vcal.components("VEVENT") if e.value("UID") == uid]
    return next((e for e in evs if e.get("RECURRENCE-ID") is None), evs[0] if evs else None)


# ---------- build / change

def _alarm(trigger, title):
    return ics.Component("VALARM", [ics.Prop("ACTION", "DISPLAY"), ics.Prop("DESCRIPTION", ics.escape(title or "Reminder")),
                                    ics.Prop("TRIGGER", ics.fmt_duration(trigger)),
                                    ics.Prop("UID", str(uuid.uuid4()).upper())])


def set_times(ev, vcal, start, end, all_day, zone_name):
    """DTSTART/DTEND (DURATION dropped). Timed values are written as TZID wall time + a VTIMEZONE."""
    ev.remove("DURATION")
    ics.put_time(ev, "DTSTART", start, all_day, zone_name)
    ics.put_time(ev, "DTEND", end, all_day, zone_name)
    if not all_day and zone_name and zone_name != "UTC":
        if not any(v.value("TZID") == zone_name for v in vcal.components("VTIMEZONE")):
            vcal.subs.insert(0, ics.vtimezone(zone_name, start.year))


def new_event(title, start, end, all_day, zone_name, location=None, notes=None, alarms=(), url=None, place=None):
    now = ics.fmt_utc(dt.datetime.now(UTC))
    uid = str(uuid.uuid4()).upper()
    ev = ics.Component("VEVENT", [ics.Prop("UID", uid), ics.Prop("DTSTAMP", now), ics.Prop("CREATED", now),
                                  ics.Prop("LAST-MODIFIED", now), ics.Prop("SEQUENCE", "0")])
    vcal = ics.Component("VCALENDAR", [ics.Prop("VERSION", "2.0"), ics.Prop("PRODID", PRODID),
                                       ics.Prop("CALSCALE", "GREGORIAN")], [ev])
    ev.set_text("SUMMARY", title)
    set_times(ev, vcal, start, end, all_day, zone_name)
    geo.put(ev, location, place)
    ev.set_text("DESCRIPTION", notes)
    if url:
        ev.set("URL", url, {"VALUE": "URI"})
    ev.set("TRANSP", "TRANSPARENT" if all_day else "OPAQUE")
    for a in alarms:
        ev.subs.append(_alarm(a, title))
    return uid, vcal


def touch(ev):
    now = ics.fmt_utc(dt.datetime.now(UTC))
    ev.set("DTSTAMP", now)
    ev.set("LAST-MODIFIED", now)
    try:
        ev.set("SEQUENCE", str(int(ev.value("SEQUENCE", "0")) + 1))
    except ValueError:
        ev.set("SEQUENCE", "1")


def replace_alarms(ev, alarms, title):
    ev.subs = [c for c in ev.subs if c.name != "VALARM"] + [_alarm(a, title) for a in alarms]


def zone_name_of(ev):
    p = ev.get("DTSTART")
    return p.params.get("TZID") if p is not None else None


# ---------- write

def put_new(session, cal, uid, vcal):
    href = cal["href"] + uid + ".ics"
    r = _write(session, "PUT", href, ics.to_text(vcal), {"If-None-Match": "*"}, cal)
    return href, r.header("ETag")


def put_existing(session, found, vcal):
    hdr = {"If-Match": found["etag"]} if found.get("etag") else {}
    r = _write(session, "PUT", found["href"], ics.to_text(vcal), hdr, found["cal"])
    return r.header("ETag")


def delete(session, found):
    hdr = {"If-Match": found["etag"]} if found.get("etag") else {}
    _write(session, "DELETE", found["href"], None, hdr, found["cal"])


def _write(session, method, href, body, hdr, cal):
    headers = dict(hdr)
    if body is not None:
        headers["Content-Type"] = "text/calendar; charset=utf-8"
    try:
        return session.mutate(method, href, body=body, headers=headers)
    except CliError as e:
        if e.status == 412:
            raise CliError(f"the event changed on the server since it was read (HTTP 412, {method} not applied): "
                           "rerun the command", status=412) from None
        if e.status == 403:
            raise CliError(f"iCloud refused the {method} in {cal['name']!r} (HTTP 403): your access to this "
                           f"{cal['kind']} calendar does not allow it", status=403) from None
        raise


def local_zone_name(cfg_tz=None):
    return cfg_tz or tzmod.local_name() or "UTC"
