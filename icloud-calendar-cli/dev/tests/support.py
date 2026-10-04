"""Shared test environment: temp ICAL_ROOT, fake credentials, profile `t`, FakeDav transport."""
import contextlib
import io
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
FIX = Path(__file__).resolve().parent / "fixtures"
TMP = tempfile.mkdtemp(prefix="icloud-calendar-test-")
PASSWORD = "abcd-efgh-ijkl-mnop"
os.environ.update(ICAL_ROOT=f"{TMP}/root", ICLOUD_APPLE_ID="me@icloud.com", ICLOUD_APP_PASSWORD=PASSWORD,
                  TZ="Europe/Lisbon")
os.environ.pop("ICAL_PROFILE", None)
sys.path.insert(0, str(ROOT))

from src import main as main_mod  # noqa: E402
from src.core import http, profile  # noqa: E402

HOME = "https://p99-caldav.icloud.com:443/1234567/calendars/"


def make_profile(name, **cfg):
    os.makedirs(f"{TMP}/root/{name}", exist_ok=True)
    Path(f"{TMP}/root/{name}/config.json").write_text(json.dumps(cfg))


def reset_profile(**cfg):
    make_profile("t", **cfg)
    Path(f"{TMP}/root/config.json").write_text(json.dumps({"default_profile": "t"}))


reset_profile()


def fixture(name):
    return (FIX / name).read_text()


class FakeDav:
    """Routes by method + URL path. Calendar resources live in self.res {path: (etag, ics)}.
    expand=True: REPORT bodies asking for <c:expand> get self.expanded[path] when present."""

    def __init__(self):
        self.calls = []
        self.res = {}
        self.expanded = {}
        self.fail = {}  # (method, path) -> status
        self.feeds = {}  # full URL -> ics text
        self.nominatim = []  # geocoder answers (JSON); default = no hit
        self.photon = {"features": []}
        self.n = 0

    def add(self, path, ics, etag=None):
        self.n += 1
        self.res[path] = (etag or f'"e{self.n}"', ics)

    def __call__(self, method, url, data, hdrs, timeout):
        body = data.decode() if data else ""
        self.calls.append({"method": method, "url": url, "body": body, "headers": dict(hdrs)})
        path = re.sub(r"^https?://[^/]+", "", url)
        if "nominatim.openstreetmap.org" in url or "photon.komoot.io" in url:
            ans = self.nominatim if "nominatim" in url else self.photon
            if ans is None:  # geocoder down
                return http.Response(503, {}, b"busy", url)
            return http.Response(200, {}, json.dumps(ans).encode(), url)
        if url in self.feeds:
            return http.Response(200, {}, self.feeds[url].encode(), url)
        if (method, path) in self.fail:
            return http.Response(self.fail[(method, path)], {}, b"<error>no</error>", url)
        if hdrs.get("Authorization") is None:
            return http.Response(401, {}, b"Unauthorized", url)
        if method == "PROPFIND":
            if path == "/":
                return self._ms(fixture("root.xml"), url)
            if path == "/1234567/principal/":
                return self._ms(fixture("principal.xml"), url)
            if path == "/1234567/calendars/":
                return self._ms(fixture("home.xml"), url)
            if path == "/1234567/notification/":
                return self._ms(fixture("notifications.xml"), url)
        if method == "GET":
            if path in self.res:
                etag, ics = self.res[path]
                return http.Response(200, {"ETag": etag}, ics.encode(), url)
            if path == "/1234567/notification/invite1.xml":
                return http.Response(200, {}, fixture("invite.xml").encode(), url)
            return http.Response(404, {}, b"", url)
        if method == "REPORT":
            return self._report(path, body, url)
        if method == "PUT":
            exists = path in self.res
            if hdrs.get("If-None-Match") == "*" and exists:
                return http.Response(412, {}, b"", url)
            if "If-Match" in hdrs and (not exists or self.res[path][0] != hdrs["If-Match"]):
                return http.Response(412, {}, b"", url)
            self.add(path, body)
            return http.Response(204 if exists else 201, {"ETag": self.res[path][0]}, b"", url)
        if method == "DELETE":
            if path not in self.res:
                return http.Response(404, {}, b"", url)
            if "If-Match" in hdrs and self.res[path][0] != hdrs["If-Match"]:
                return http.Response(412, {}, b"", url)
            del self.res[path]
            return http.Response(204, {}, b"", url)
        return http.Response(405, {}, b"", url)

    def _report(self, path, body, url):
        m = re.search(r'<c:text-match[^>]*>([^<]*)<', body)
        out = []
        for p, (etag, ics) in sorted(self.res.items()):
            if not p.startswith(path):
                continue
            if m and m.group(1) not in ics:
                continue
            data = self.expanded.get(p, ics) if "<c:expand" in body else ics
            out.append(f"<d:response><d:href>{p}</d:href><d:propstat><d:prop><d:getetag>{etag}</d:getetag>"
                       f"<c:calendar-data>{_x(data)}</c:calendar-data></d:prop>"
                       "<d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>")
        xml = ('<?xml version="1.0"?><d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
               + "".join(out) + "</d:multistatus>")
        return http.Response(207, {}, xml.encode(), url)

    def _ms(self, text, url):
        return http.Response(207, {}, text.encode(), url)

    def puts(self):
        return [c for c in self.calls if c["method"] in ("PUT", "DELETE")]


def _x(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def run(*argv, stdin=None, fake=None):
    out, err = io.StringIO(), io.StringIO()
    stdin_obj = io.StringIO(stdin) if stdin is not None else io.StringIO("")
    stdin_obj.isatty = lambda: stdin is None
    patches = [mock.patch.object(sys, "stdin", stdin_obj)]
    if fake is not None:
        patches.append(mock.patch.object(http, "_send", fake))
    with contextlib.ExitStack() as st:
        for p in patches:
            st.enter_context(p)
        st.enter_context(contextlib.redirect_stdout(out))
        st.enter_context(contextlib.redirect_stderr(err))
        rc = main_mod.main(list(argv))
    profile.resolve("t", "create")
    return rc, out.getvalue(), err.getvalue()
