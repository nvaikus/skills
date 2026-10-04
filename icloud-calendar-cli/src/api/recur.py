"""Minimal local RRULE expansion, used only when the server returns a recurring master unexpanded
(and for subscribed webcal feeds). Supported: FREQ DAILY/WEEKLY/MONTHLY/YEARLY, INTERVAL, COUNT, UNTIL,
BYDAY (with ordinals in MONTHLY/YEARLY+BYMONTH), BYMONTHDAY, BYMONTH, BYSETPOS, WKST.
Anything else raises Unsupported: the caller shows the first occurrence and says so."""
import calendar as _cal
import datetime as dt

DAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
MAX_PERIODS = 20000


class Unsupported(Exception):
    pass


def parse_rule(s):
    rule = {}
    for part in (s or "").split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            rule[k.strip().upper()] = v.strip()
    return rule


def _byday(v):
    out = []
    for item in v.split(","):
        item = item.strip().upper()
        n, d = item[:-2], item[-2:]
        if d not in DAYS:
            raise Unsupported(f"BYDAY={v}")
        out.append((int(n) if n not in ("", "+") else None, DAYS.index(d)))
    return out


def _month_days(year, month, rule, anchor_day):
    last = _cal.monthrange(year, month)[1]
    days = set()
    if "BYMONTHDAY" in rule:
        for x in rule["BYMONTHDAY"].split(","):
            n = int(x)
            d = n if n > 0 else last + 1 + n
            if 1 <= d <= last:
                days.add(d)
    if "BYDAY" in rule:
        bd = set()
        for nth, wd in _byday(rule["BYDAY"]):
            matches = [d for d in range(1, last + 1) if dt.date(year, month, d).weekday() == wd]
            if nth is None:
                bd.update(matches)
            elif -len(matches) <= nth <= len(matches) and nth != 0:
                bd.add(matches[nth - 1] if nth > 0 else matches[nth])
        days = (days & bd) if "BYMONTHDAY" in rule else bd
    if "BYMONTHDAY" not in rule and "BYDAY" not in rule and anchor_day <= last:
        days.add(anchor_day)
    return [dt.date(year, month, d) for d in sorted(days)]


def _add_months(d, n):
    m = d.month - 1 + n
    return d.year + m // 12, m % 12 + 1


def _period_dates(freq, start, k, interval, rule):
    """Candidate dates of period k (before BYSETPOS)."""
    if freq == "DAILY":
        d = start + dt.timedelta(days=k * interval)
        ok = True
        if "BYMONTH" in rule:
            ok = d.month in {int(x) for x in rule["BYMONTH"].split(",")}
        if ok and "BYDAY" in rule:
            ok = d.weekday() in {wd for _, wd in _byday(rule["BYDAY"])}
        if ok and "BYMONTHDAY" in rule:
            ok = d in _month_days(d.year, d.month, {"BYMONTHDAY": rule["BYMONTHDAY"]}, d.day)
        return [d] if ok else []
    if freq == "WEEKLY":
        wkst = DAYS.index(rule.get("WKST", "MO").upper()) if rule.get("WKST", "MO").upper() in DAYS else 0
        week0 = start - dt.timedelta(days=(start.weekday() - wkst) % 7)
        ws = week0 + dt.timedelta(weeks=k * interval)
        wds = [wd for _, wd in _byday(rule["BYDAY"])] if "BYDAY" in rule else [start.weekday()]
        out = sorted(ws + dt.timedelta(days=(wd - wkst) % 7) for wd in set(wds))
        if "BYMONTH" in rule:
            months = {int(x) for x in rule["BYMONTH"].split(",")}
            out = [d for d in out if d.month in months]
        return out
    if freq == "MONTHLY":
        y, m = _add_months(start, k * interval)
        if "BYMONTH" in rule and m not in {int(x) for x in rule["BYMONTH"].split(",")}:
            return []
        return _month_days(y, m, rule, start.day)
    if freq == "YEARLY":
        y = start.year + k * interval
        months = sorted({int(x) for x in rule["BYMONTH"].split(",")}) if "BYMONTH" in rule else [start.month]
        if "BYDAY" in rule and "BYMONTH" not in rule and any(n is not None for n, _ in _byday(rule["BYDAY"])):
            raise Unsupported("YEARLY BYDAY with ordinal and no BYMONTH")
        if "BYMONTH" not in rule and ("BYDAY" in rule or "BYMONTHDAY" in rule):
            months = list(range(1, 13))
        out = []
        for m in months:
            out += _month_days(y, m, rule, start.day)
        return out
    raise Unsupported(f"FREQ={freq}")


def occurrences(dtstart, rule_s, until_limit, extra=(), exdates=()):
    """Occurrence starts (date or aware datetime, same kind as dtstart) from dtstart up to until_limit
    (exclusive). DST-safe: wall time is kept in dtstart's zone."""
    rule = parse_rule(rule_s)
    for bad in ("BYHOUR", "BYMINUTE", "BYSECOND", "BYWEEKNO", "BYYEARDAY"):
        if bad in rule:
            raise Unsupported(bad)
    freq = rule.get("FREQ", "").upper()
    interval = int(rule.get("INTERVAL", "1") or 1)
    count = int(rule["COUNT"]) if "COUNT" in rule else None
    is_date = not isinstance(dtstart, dt.datetime)
    until = None
    if "UNTIL" in rule:
        from .ics import parse_raw
        u, u_is_date = parse_raw(rule["UNTIL"], {}, local=None if is_date else dtstart.tzinfo)
        until = u if is_date else (dt.datetime.combine(u, dt.time(23, 59, 59), dtstart.tzinfo) if u_is_date else u)
        if is_date and isinstance(until, dt.datetime):
            until = until.date()
    start_date = dtstart if is_date else dtstart.date()

    def mk(d):
        return d if is_date else dt.datetime.combine(d, dtstart.timetz().replace(tzinfo=None), dtstart.tzinfo)

    ex = set(_key(x) for x in exdates)
    out, n = [], 0
    for k in range(MAX_PERIODS):
        cands = _period_dates(freq, start_date, k, interval, rule)
        if "BYSETPOS" in rule and cands:
            pos = [int(x) for x in rule["BYSETPOS"].split(",")]
            cands = sorted({cands[p - 1] if p > 0 else cands[p] for p in pos if -len(cands) <= p <= len(cands) and p})
        stop = False
        for d in cands:
            if d < start_date:
                continue
            t = mk(d)
            if until is not None and t > until:
                stop = True
                break
            n += 1
            if count is not None and n > count:
                stop = True
                break
            if t >= until_limit:
                stop = True
                break
            if _key(t) not in ex:
                out.append(t)
        if stop:
            break
        # empty periods are fine (e.g. Feb 30); give up only on MAX_PERIODS
    out += [x for x in extra if x < until_limit and _key(x) not in ex]
    return sorted(set(out), key=_sortkey)


def _key(t):
    if isinstance(t, dt.datetime):
        return t.astimezone(dt.timezone.utc).replace(tzinfo=None) if t.tzinfo else t
    return t


def _sortkey(t):
    if isinstance(t, dt.datetime):
        return _key(t)
    return dt.datetime.combine(t, dt.time())
