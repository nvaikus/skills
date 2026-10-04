"""CalDAV transport: Basic auth session, PROPFIND / REPORT / GET / PUT / DELETE, multistatus parsing.
The only module that passes allow_mutate (in `mutate`)."""
import os
import subprocess
import urllib.parse
import xml.etree.ElementTree as ET

from ..core import http
from ..core.errors import AuthError, CliError, UsageError

NS = {"D": "DAV:", "C": "urn:ietf:params:xml:ns:caldav", "CS": "http://calendarserver.org/ns/",
      "A": "http://apple.com/ns/ical/", "ME": "http://me.com/_namespace/"}
ROOT_URL = "https://caldav.icloud.com/"
for _p, _u in NS.items():
    ET.register_namespace(_p.lower() if _p != "D" else "d", _u)


def q(tag):
    """'D:href' -> '{DAV:}href'."""
    p, local = tag.split(":", 1)
    return f"{{{NS[p]}}}{local}"


def xml_body(root_tag, inner):
    """root_tag 'D:propfind', inner = raw XML using d:/c:/cs:/a: prefixes."""
    p, local = root_tag.split(":")
    return ('<?xml version="1.0" encoding="utf-8"?>'
            f'<{p.lower()}:{local} xmlns:d="DAV:" xmlns:c="{NS["C"]}" xmlns:cs="{NS["CS"]}" xmlns:a="{NS["A"]}"'
            f' xmlns:me="{NS["ME"]}">{inner}</{p.lower()}:{local}>')


def credentials(cfg):
    """(apple_id, password) from env / password_cmd. The password never reaches argv, files or output."""
    apple_id = os.environ.get(cfg.get("apple_id_env") or "ICLOUD_APPLE_ID") or cfg.get("apple_id")
    pw_env = cfg.get("password_env") or "ICLOUD_APP_PASSWORD"
    pw = os.environ.get(pw_env)
    if not pw and cfg.get("password_cmd"):
        try:
            out = subprocess.run(cfg["password_cmd"], shell=True, capture_output=True, text=True, timeout=30)
            pw = out.stdout.strip() if out.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
            pw = None
    if not apple_id or not pw:
        miss = [w for w, v in (("Apple ID", apple_id), (f"password (${pw_env})", pw)) if not v]
        raise UsageError(f"no {' and no '.join(miss)} in this environment: run `icloud-calendar onboard`"
                         " (a fresh shell / Claude restart is needed after adding the export)")
    return apple_id, pw.strip()


class Session:
    def __init__(self, cfg):
        self.cfg = cfg
        self.auth = credentials(cfg)

    def _call(self, method, url, body=None, headers=None, depth=None, ok=(200, 207), mutate=False):
        hdrs = dict(headers or {})
        if body is not None and "Content-Type" not in hdrs:
            hdrs["Content-Type"] = "application/xml; charset=utf-8"
        if depth is not None:
            hdrs["Depth"] = str(depth)
        try:
            return http.request(method, url, body=body, headers=hdrs, auth=self.auth, allow_mutate=mutate, ok=ok)
        except CliError as e:
            if e.status == 401:
                raise AuthError("iCloud rejected the Apple ID / app-specific password (HTTP 401): check "
                                 f"${self.cfg.get('password_env')} holds a current app-specific password "
                                 "(account.apple.com > Sign-In and Security > App-Specific Passwords); "
                                 "rerun `icloud-calendar onboard`") from None
            raise

    def propfind(self, url, props, depth=0):
        """props: raw '<d:prop>...</d:prop>' -> [Item]."""
        r = self._call("PROPFIND", url, xml_body("D:propfind", props), depth=depth)
        return parse_multistatus(r.text, r.url)

    def report(self, url, root_tag, inner, depth=1):
        r = self._call("REPORT", url, xml_body(root_tag, inner), depth=depth)
        return parse_multistatus(r.text, r.url)

    def get(self, url):
        return self._call("GET", url, ok=(200,))

    def mutate(self, method, url, body=None, headers=None):
        return self._call(method, url, body=body, headers=headers, ok=(200, 201, 204), mutate=True)


class Item:
    """One <response>: absolute href + props with status 200 (qname -> Element)."""

    def __init__(self, href, props, status=None):
        self.href, self.props, self.status = href, props, status

    def el(self, tag):
        return self.props.get(q(tag))

    def text(self, tag):
        e = self.el(tag)
        return (e.text or "").strip() if e is not None and e.text else None

    def href_of(self, tag):
        """<prop><x><d:href>..</d:href></x></prop> -> href text or None."""
        e = self.el(tag)
        h = e.find(q("D:href")) if e is not None else None
        return h.text.strip() if h is not None and h.text else None

    def has(self, tag):
        return q(tag) in self.props


def parse_multistatus(text, base):
    try:
        root = ET.fromstring(text.encode("utf-8") if isinstance(text, str) else text)
    except ET.ParseError as e:
        raise CliError(f"unparseable multistatus from {base}: {e}") from None
    items = []
    for resp in root.findall(q("D:response")):
        h = resp.find(q("D:href"))
        href = urllib.parse.urljoin(base, (h.text or "").strip()) if h is not None else base
        props = {}
        for ps in resp.findall(q("D:propstat")):
            st = ps.find(q("D:status"))
            if st is not None and " 200 " not in f"{st.text} ":
                continue
            prop = ps.find(q("D:prop"))
            for child in list(prop if prop is not None else []):
                props[child.tag] = child
        st = resp.find(q("D:status"))
        items.append(Item(href, props, st.text.strip() if st is not None and st.text else None))
    return items


def same_path(a, b):
    """Two hrefs name the same resource (host may differ: caldav vs pNN-caldav, :443)."""
    pa, pb = urllib.parse.urlsplit(a).path, urllib.parse.urlsplit(b).path
    return urllib.parse.unquote(pa).rstrip("/") == urllib.parse.unquote(pb).rstrip("/")
