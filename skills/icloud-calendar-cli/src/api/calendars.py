"""Discovery (principal -> calendar home, cached per profile), the calendar list with its kind and
access, calendar choice by name/id, and the per-kind write gate."""
import urllib.parse

from ..core import config
from ..core.errors import CliError, UsageError
from .dav import ROOT_URL, Session, q

PRINCIPAL_PROPS = ("<d:prop><c:calendar-home-set/><c:calendar-user-address-set/><cs:notification-URL/>"
                   "<d:displayname/></d:prop>")
CAL_PROPS = ("<d:prop><d:resourcetype/><d:displayname/><a:calendar-color/><a:calendar-order/>"
             "<c:supported-calendar-component-set/><d:current-user-privilege-set/><d:owner/>"
             "<cs:invite/><cs:source/><cs:publish-url/><cs:getctag/><c:calendar-description/></d:prop>")
WRITE_PRIVS = {"write", "write-content", "bind", "all"}

KINDS = {
    "own": "yours, not shared",
    "shared-by-me": "yours, shared with others (they see changes; iCloud may notify them)",
    "shared-with-me": "someone else's, shared with you",
    "subscribed": "subscription (webcal feed, holidays): read-only",
    "reminders": "Reminders/VTODO list: not for events",
}


def discover(session, profile_name=None):
    """-> cfg with principal/home/notifications/user_addresses (written to the profile)."""
    items = session.propfind(ROOT_URL, "<d:prop><d:current-user-principal/></d:prop>", depth=0)
    principal = next((i.href_of("D:current-user-principal") for i in items if i.has("D:current-user-principal")), None)
    if not principal:
        raise CliError("iCloud returned no current-user-principal (unexpected PROPFIND answer)")
    principal = urllib.parse.urljoin(ROOT_URL, principal)
    items = session.propfind(principal, PRINCIPAL_PROPS, depth=0)
    it = items[0] if items else None
    home = it.href_of("C:calendar-home-set") if it else None
    if not home:
        raise CliError("iCloud returned no calendar-home-set for the principal")
    home = urllib.parse.urljoin(principal, home)
    notif = it.href_of("CS:notification-URL")
    addrs = []
    el = it.el("C:calendar-user-address-set")
    if el is not None:
        addrs = [h.text.strip() for h in el.findall(q("D:href")) if h.text]
    return config.update(profile_name, principal=principal, home=home,
                         notifications=urllib.parse.urljoin(home, notif) if notif else None, user_addresses=addrs)


def session_for(cfg, profile_name=None):
    """Session + cfg with a calendar home (discovers once, then cached)."""
    s = Session(cfg)
    if not cfg.get("home"):
        cfg = discover(s, profile_name)
        s.cfg = cfg
    return s, cfg


def _children(el):
    return [c.tag for c in list(el)] if el is not None else []


def _privs(item):
    el = item.el("D:current-user-privilege-set")
    if el is None:
        return None
    out = set()
    for p in el.iter(q("D:privilege")):
        for c in list(p):
            out.add(c.tag.split("}")[-1])
    return out


def _person(el):
    """<cs:organizer>/<cs:user>: common-name, else first+last, else the mailto address."""
    if el is None:
        return None
    cn = el.find(q("CS:common-name"))
    if cn is not None and (cn.text or "").strip():
        return cn.text.strip()
    names = [(el.find(q(t)).text or "").strip() for t in ("CS:first-name", "CS:last-name") if el.find(q(t)) is not None]
    if any(names):
        return " ".join(n for n in names if n)
    h = el.find(q("D:href"))
    return (h.text or "").strip().replace("mailto:", "") if h is not None else None


def _invite(item, my_addrs):
    """-> (organizer, sharees[{who, access, status}], my_access 'rw'|'ro'|None) from CS:invite."""
    el = item.el("CS:invite")
    if el is None:
        return None, [], None
    org = _person(el.find(q("CS:organizer")))
    sharees, mine = [], None
    mine_l = {a.lower() for a in my_addrs or []}
    for u in el.findall(q("CS:user")):
        acc = u.find(q("CS:access"))
        access = "rw" if acc is not None and acc.find(q("CS:read-write")) is not None else "ro"
        status = next((t.split("}")[-1].replace("invite-", "") for t in _children(u)
                       if t.split("}")[-1].startswith("invite-")), None)
        h = u.find(q("D:href"))
        addr = (h.text or "").strip() if h is not None else ""
        sharees.append({"who": _person(u), "access": access, "status": status})
        if addr.lower() in mine_l:
            mine = access
    return org, sharees, mine


def classify(item, my_addrs=()):
    """PROPFIND item -> calendar dict, or None for non-calendar resources (inbox, outbox, notifications)."""
    rt = set(_children(item.el("D:resourcetype")))
    is_cal, subscribed = q("C:calendar") in rt, q("CS:subscribed") in rt
    if not is_cal and not subscribed:
        return None
    comps_el = item.el("C:supported-calendar-component-set")
    comps = sorted({c.get("name", "").upper() for c in list(comps_el)} - {""}) if comps_el is not None else []
    comps = comps or ["VEVENT", "VTODO"]
    org, sharees, my_access = _invite(item, my_addrs)
    privs = _privs(item)
    if subscribed:
        kind = "subscribed"
    elif "VEVENT" not in comps:
        kind = "reminders"
    elif q("CS:shared") in rt:
        kind = "shared-with-me"
    elif q("CS:shared-owner") in rt:
        kind = "shared-by-me"
    else:
        kind = "own"
    if kind == "subscribed":
        access = "ro"
    elif privs is not None:
        access = "rw" if privs & WRITE_PRIVS else "ro"
    elif kind == "shared-with-me":
        access = my_access or "ro"
    else:
        access = "rw"
    owner = "me" if kind in ("own", "shared-by-me", "reminders") and q("CS:shared") not in rt else None
    if kind == "shared-with-me" or (kind == "reminders" and q("CS:shared") in rt):
        owner = org or item.href_of("D:owner") or "?"
    source = item.href_of("CS:source")
    if kind == "subscribed":
        owner = urllib.parse.urlsplit(source or "").hostname or "?"
    color = (item.text("A:calendar-color") or "")[:7] or None
    href = item.href if item.href.endswith("/") else item.href + "/"
    return {"name": item.text("D:displayname") or href.rstrip("/").rsplit("/", 1)[-1],
            "kind": kind, "access": access, "owner": owner, "comps": ",".join(comps), "color": color,
            "sharees": len(sharees) if kind == "shared-by-me" else None,
            "published": item.has("CS:publish-url") and bool(item.href_of("CS:publish-url")),
            "id": href.rstrip("/").rsplit("/", 1)[-1], "href": href, "source": source,
            "order": int(item.text("A:calendar-order") or 0) if (item.text("A:calendar-order") or "").isdigit() else 0,
            "ctag": item.text("CS:getctag"), "description": item.text("C:calendar-description"),
            "privileges": sorted(privs) if privs is not None else None, "sharee_list": sharees,
            "events": kind != "reminders" and "VEVENT" in comps}


def list_all(session, cfg):
    items = session.propfind(cfg["home"], CAL_PROPS, depth=1)
    cals = [c for c in (classify(i, cfg.get("user_addresses")) for i in items) if c]
    return sorted(cals, key=lambda c: (c["order"], c["name"].lower()))


def pick(cals, spec, what="calendar"):
    """Name (case-insensitive, then unique substring), id or href -> one calendar; else exit 2 with candidates."""
    if not spec:
        raise UsageError(f"no {what} given")
    s = spec.strip()
    low = s.lower()
    for test in (lambda c: c["id"] == s or c["href"] == s or c["href"].rstrip("/").endswith("/" + s.strip("/")),
                 lambda c: c["name"].lower() == low,
                 lambda c: low in c["name"].lower()):
        hits = [c for c in cals if test(c)]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            raise UsageError(f"{what} {spec!r} is ambiguous: pass the id", payload=_cands(hits))
    raise UsageError(f"no {what} {spec!r}; calendars:", payload=_cands(cals))


def _cands(cals):
    return [{"name": c["name"], "kind": c["kind"], "access": c["access"], "id": c["id"]} for c in cals]


def write_gate(cal):
    """Refuse writes the server would refuse or that make no sense, with the reason per kind."""
    if cal["kind"] == "reminders":
        raise UsageError(f"{cal['name']!r} is a Reminders (VTODO) list, not an event calendar")
    if cal["kind"] == "subscribed":
        raise UsageError(f"{cal['name']!r} is a subscribed calendar (feed from {cal['owner']}): read-only; "
                         "changes belong in the feed's source")
    if cal["access"] != "rw":
        who = f" (owner: {cal['owner']})" if cal.get("owner") and cal["owner"] != "me" else ""
        raise UsageError(f"{cal['name']!r} is shared with you read-only{who}: ask the owner for edit access, "
                         "or pick another calendar")


def choose_for_write(cals, spec, cfg):
    """--cal, else the profile default, else the only writable event calendar."""
    events = [c for c in cals if c["events"]]
    if spec:
        cal = pick(cals, spec)
    elif cfg.get("default_calendar"):
        hits = [c for c in events if c["id"] == cfg["default_calendar"]]
        if not hits:
            raise UsageError(f"default calendar id {cfg['default_calendar']!r} no longer exists: pass --cal or "
                             "`icloud-calendar calendars --set-default NAME`", payload=_cands(events))
        cal = hits[0]
    else:
        rw = [c for c in events if c["access"] == "rw" and c["kind"] != "subscribed"]
        if len(rw) != 1:
            raise UsageError("which calendar? pass --cal NAME, or set one: `icloud-calendar calendars --set-default NAME`",
                             payload=_cands(rw or events))
        cal = rw[0]
    write_gate(cal)
    return cal
