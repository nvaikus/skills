"""iCalendar (RFC 5545) read/write that keeps every property it does not understand: parse into
Component trees of raw content lines, change only what the user asked, serialize with folding.
Also: date-time values <-> Python, and VTIMEZONE generation from zoneinfo."""
import datetime as dt
import re

from . import tz as tzmod

UTC = dt.timezone.utc


class Prop:
    __slots__ = ("name", "params", "value")

    def __init__(self, name, value="", params=None):
        self.name, self.value, self.params = name.upper(), value, dict(params or {})

    def line(self):
        ps = "".join(f";{k}={_qparam(v)}" for k, v in self.params.items())
        return f"{self.name}{ps}:{self.value}"


class Component:
    def __init__(self, name, props=None, subs=None):
        self.name, self.props, self.subs = name.upper(), list(props or []), list(subs or [])

    def get(self, name):
        name = name.upper()
        return next((p for p in self.props if p.name == name), None)

    def all(self, name):
        name = name.upper()
        return [p for p in self.props if p.name == name]

    def value(self, name, default=None):
        p = self.get(name)
        return p.value if p else default

    def text(self, name):
        p = self.get(name)
        return unescape(p.value) if p else None

    def remove(self, name):
        self.props = [p for p in self.props if p.name != name.upper()]

    def set(self, name, value, params=None):
        """Replace (first position kept) or append."""
        name = name.upper()
        new = Prop(name, value, params)
        for i, p in enumerate(self.props):
            if p.name == name:
                self.props[i] = new
                self.props = [x for j, x in enumerate(self.props) if x.name != name or j == i]
                return new
        self.props.append(new)
        return new

    def set_text(self, name, text):
        if text is None or text == "":
            self.remove(name)
        else:
            self.set(name, escape(text))

    def components(self, name):
        return [c for c in self.subs if c.name == name.upper()]

    def serialize(self):
        out = [f"BEGIN:{self.name}"] + [fold(p.line()) for p in self.props]
        out += [c.serialize() for c in self.subs]
        out.append(f"END:{self.name}")
        return "\r\n".join(out)


def to_text(cal):
    return cal.serialize() + "\r\n"


# ---------- parse

def unfold(text):
    lines = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        elif raw.strip():
            lines.append(raw)
    return lines


def _split_line(line):
    """'DTSTART;TZID="A:B";VALUE=X:2026...' -> (name, params, value), honouring quoted ':' and ';'."""
    i, inq, cut = 0, False, []
    colon = None
    for i, ch in enumerate(line):
        if ch == '"':
            inq = not inq
        elif not inq and ch == ";" and colon is None:
            cut.append(i)
        elif not inq and ch == ":":
            colon = i
            break
    if colon is None:
        return line.upper(), {}, ""
    head, value = line[:colon], line[colon + 1:]
    bounds = [-1] + cut + [colon]
    parts = [head[bounds[k] + 1:bounds[k + 1]] for k in range(len(bounds) - 1)]
    name, params = parts[0], {}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            params[k.upper()] = v[1:-1] if len(v) >= 2 and v[0] == v[-1] == '"' else v
    return name.upper(), params, value


def parse(text):
    """-> top Component (VCALENDAR). Tolerant: stray lines outside BEGIN/END are dropped."""
    stack, top = [], None
    for line in unfold(text):
        name, params, value = _split_line(line)
        if name == "BEGIN":
            c = Component(value.strip())
            if stack:
                stack[-1].subs.append(c)
            stack.append(c)
        elif name == "END":
            if stack:
                c = stack.pop()
                if not stack:
                    top = top or c
        elif stack:
            stack[-1].props.append(Prop(name, value, params))
    if top is None and stack:
        top = stack[0]
    if top is None:
        raise ValueError("no BEGIN:VCALENDAR in calendar data")
    return top


# ---------- text values

def unescape(v):
    return re.sub(r"\\([\\;,nN])", lambda m: "\n" if m.group(1) in "nN" else m.group(1), v or "")


def escape(v):
    return (v.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\n").replace("\n", "\\n"))


def _qparam(v):
    return f'"{v}"' if any(c in v for c in ':;,') else v


def fold(line):
    """75-octet folding, never splitting a UTF-8 sequence."""
    b = line.encode("utf-8")
    if len(b) <= 75:
        return line
    out, cur, size, limit = [], "", 0, 75
    for ch in line:
        n = len(ch.encode("utf-8"))
        if size + n > limit:
            out.append(cur)
            cur, size, limit = "", 0, 74
        cur += ch
        size += n
    out.append(cur)
    return "\r\n ".join(out)


# ---------- date-time values

def parse_value(prop, cal=None, local=None):
    """DTSTART/DTEND/RECURRENCE-ID/EXDATE item -> (date | aware datetime, is_date)."""
    return parse_raw(prop.value, prop.params, cal, local)


def parse_raw(value, params, cal=None, local=None):
    v = value.strip()
    if params.get("VALUE", "").upper() == "DATE" or re.fullmatch(r"\d{8}", v):
        return dt.datetime.strptime(v[:8], "%Y%m%d").date(), True
    naive = dt.datetime.strptime(v.rstrip("Zz")[:15], "%Y%m%dT%H%M%S")
    if v.upper().endswith("Z"):
        return naive.replace(tzinfo=UTC), False
    tzid = params.get("TZID")
    zone = tzmod.resolve(tzid, cal) if tzid else (local or tzmod.local())
    return naive.replace(tzinfo=zone), False


def list_values(prop, cal=None, local=None):
    """EXDATE/RDATE may hold several comma-separated values."""
    return [parse_raw(x, prop.params, cal, local)[0] for x in prop.value.split(",") if x.strip()]


def fmt_date(d):
    return d.strftime("%Y%m%d")


def fmt_utc(t):
    return t.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def fmt_local(t):
    return t.strftime("%Y%m%dT%H%M%S")


def put_time(comp, name, value, is_date, zone_name=None):
    """Write DTSTART/DTEND: VALUE=DATE, TZID=zone wall time, or UTC."""
    if is_date:
        comp.set(name, fmt_date(value), {"VALUE": "DATE"})
    elif zone_name and zone_name != "UTC":
        comp.set(name, fmt_local(value.astimezone(tzmod.zone(zone_name))), {"TZID": zone_name})
    else:
        comp.set(name, fmt_utc(value))


def parse_duration(v):
    m = re.fullmatch(r"([+-]?)P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", (v or "").strip())
    if not m:
        raise ValueError(f"bad duration {v!r}")
    sign = -1 if m.group(1) == "-" else 1
    w, d, h, mi, s = (int(x or 0) for x in m.groups()[1:])
    return sign * dt.timedelta(weeks=w, days=d, hours=h, minutes=mi, seconds=s)


def fmt_duration(td):
    sign = "-" if td < dt.timedelta(0) else ""
    secs = int(abs(td.total_seconds()))
    days, rem = divmod(secs, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    out = f"{sign}P" + (f"{days}D" if days else "")
    t = (f"{h}H" if h else "") + (f"{m}M" if m else "") + (f"{s}S" if s else "")
    if t:
        out += "T" + t
    return out if out not in ("P", "-P") else "PT0S"


# ---------- VTIMEZONE from zoneinfo

def _offset(o):
    sign = "-" if o < dt.timedelta(0) else "+"
    mins = int(abs(o.total_seconds()) // 60)
    return f"{sign}{mins // 60:02d}{mins % 60:02d}"


def _transitions(zone, year):
    """UTC instants where zone's offset changes in [year-1, year+1]."""
    out = []
    t = dt.datetime(year - 1, 1, 1, tzinfo=UTC)
    end = dt.datetime(year + 2, 1, 1, tzinfo=UTC)
    prev = t.astimezone(zone).utcoffset()
    step = dt.timedelta(days=1)
    while t < end:
        n = t + step
        off = n.astimezone(zone).utcoffset()
        if off != prev:
            lo, hi = t, n
            while hi - lo > dt.timedelta(minutes=1):
                mid = lo + (hi - lo) / 2
                if mid.astimezone(zone).utcoffset() == prev:
                    lo = mid
                else:
                    hi = mid
            out.append((hi.replace(second=0, microsecond=0), prev, off))
            prev = off
        t = n
    return out


def vtimezone(zone_name, year):
    zone = tzmod.zone(zone_name)
    c = Component("VTIMEZONE", [Prop("TZID", zone_name)])
    trans = _transitions(zone, year)
    if not trans:
        off = dt.datetime(year, 6, 1, tzinfo=UTC).astimezone(zone).utcoffset()
        c.subs.append(Component("STANDARD", [Prop("DTSTART", "19700101T000000"), Prop("TZOFFSETFROM", _offset(off)),
                                             Prop("TZOFFSETTO", _offset(off))]))
        return c
    for at, before, after in trans:
        local_onset = (at + before).replace(tzinfo=None)
        is_dst = bool((at + dt.timedelta(minutes=1)).astimezone(zone).dst())
        name = (at + dt.timedelta(minutes=1)).astimezone(zone).tzname() or ""
        props = [Prop("DTSTART", fmt_local(local_onset)), Prop("TZOFFSETFROM", _offset(before)),
                 Prop("TZOFFSETTO", _offset(after))]
        if name and not re.fullmatch(r"[+-]\d+", name):
            props.append(Prop("TZNAME", name))
        c.subs.append(Component("DAYLIGHT" if is_dst else "STANDARD", props))
    return c
