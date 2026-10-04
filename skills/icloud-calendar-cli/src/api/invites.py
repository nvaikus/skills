"""Pending calendar-share invitations from the CalendarServer notification collection."""
import xml.etree.ElementTree as ET

from ..core.errors import CliError
from .calendars import _person
from .dav import q


def parse(xml_text):
    """One notification resource -> invite dict or None (other notification types)."""
    try:
        root = ET.fromstring(xml_text.encode("utf-8"))
    except ET.ParseError:
        return None
    inv = root if root.tag == q("CS:invite-notification") else root.find(q("CS:invite-notification"))
    if inv is None:
        return None
    acc = inv.find(q("CS:access"))
    access = "rw" if acc is not None and acc.find(q("CS:read-write")) is not None else "ro"
    status = next((c.tag.split("}")[-1].replace("invite-", "") for c in list(inv)
                   if c.tag.split("}")[-1].startswith("invite-")), None)
    host = inv.find(q("CS:hosturl"))
    hh = host.find(q("D:href")) if host is not None else None
    uid = inv.find(q("CS:uid"))
    summ = inv.find(q("CS:summary"))
    return {"calendar": (summ.text or "").strip() if summ is not None else "",
            "from": _person(inv.find(q("CS:organizer"))), "access": access, "status": status,
            "uid": (uid.text or "").strip() if uid is not None else None,
            "host": (hh.text or "").strip() if hh is not None else None}


def pending(session, cfg):
    url = cfg.get("notifications")
    if not url:
        return []
    items = session.propfind(url, "<d:prop><cs:notificationtype/><d:getetag/></d:prop>", depth=1)
    out = []
    for it in items:
        nt = it.el("CS:notificationtype")
        if nt is None or nt.find(q("CS:invite-notification")) is None:
            continue
        try:
            inv = parse(session.get(it.href).text)
        except CliError:
            continue
        if inv and inv["status"] in (None, "noresponse"):
            out.append(inv)
    return out
