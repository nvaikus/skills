"""Contract tests over FakeDav (no network). Run: python3 -m unittest discover -s dev/tests"""
import json
import re
import os
import subprocess
import unittest
from unittest import mock

from support import HOME, PASSWORD, ROOT, FakeDav, reset_profile, run  # noqa: E402

from src.core import config  # noqa: E402

WEEKLY = """BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Apple Inc.//macOS//EN\r\nBEGIN:VTIMEZONE\r\nTZID:Europe/Lisbon\r\nEND:VTIMEZONE\r
BEGIN:VEVENT\r\nUID:WEEKLY-1\r\nSUMMARY:Standup\r\nDTSTART;TZID=Europe/Lisbon:20261005T093000\r
DTEND;TZID=Europe/Lisbon:20261005T094500\r\nRRULE:FREQ=WEEKLY;BYDAY=MO,WE\r\nEXDATE;TZID=Europe/Lisbon:20261007T093000\r
X-APPLE-TRAVEL-ADVISORY-BEHAVIOR:AUTOMATIC\r\nSEQUENCE:2\r\nBEGIN:VALARM\r\nACTION:DISPLAY\r\nTRIGGER:-PT15M\r\nEND:VALARM\r\nEND:VEVENT\r
BEGIN:VEVENT\r\nUID:WEEKLY-1\r\nRECURRENCE-ID;TZID=Europe/Lisbon:20261012T093000\r\nSUMMARY:Standup (late)\r
DTSTART;TZID=Europe/Lisbon:20261012T110000\r\nDTEND;TZID=Europe/Lisbon:20261012T111500\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"""

SINGLE = """BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:SINGLE-ABCDEF\r\nSUMMARY:Lunch\\, with Bob\r
DTSTART:20261006T120000Z\r\nDTEND:20261006T130000Z\r\nLOCATION:Cafe\r\nDESCRIPTION:line1\\nline2\r\nX-KEEP-ME;X-P=1:yes\r
END:VEVENT\r\nEND:VCALENDAR\r\n"""

EXPANDED = """BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:SRV-1\r\nSUMMARY:Gym\r\nRECURRENCE-ID:20261005T170000Z\r
DTSTART:20261005T170000Z\r\nDTEND:20261005T180000Z\r\nEND:VEVENT\r\nBEGIN:VEVENT\r\nUID:SRV-1\r\nSUMMARY:Gym\r
RECURRENCE-ID:20261006T170000Z\r\nDTSTART:20261006T170000Z\r\nDTEND:20261006T180000Z\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"""

FEED = """BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:hol-1\r\nSUMMARY:Republic Day\r\nDTSTART;VALUE=DATE:20261005\r
DTEND;VALUE=DATE:20261006\r\nRRULE:FREQ=YEARLY\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"""

P = "/1234567/calendars/"


def tsv(out):
    lines = out.strip().split("\n")
    head = lines[0].split("\t")
    return [dict(zip(head, ln.split("\t"))) for ln in lines[1:]]


class Base(unittest.TestCase):
    def setUp(self):
        reset_profile()
        self.dav = FakeDav()

    def cli(self, *argv, **kw):
        return run(*argv, fake=self.dav, **kw)


class TestDiscoveryAndKinds(Base):
    def test_discovery_cached(self):
        rc, out, err = self.cli("calendars")
        self.assertEqual(rc, 0, err)
        cfg = config.load("t")
        self.assertEqual(cfg["home"], HOME)
        self.assertEqual(cfg["notifications"], "https://p99-caldav.icloud.com:443/1234567/notification/")
        self.assertIn("mailto:me@icloud.com", cfg["user_addresses"])
        n = len(self.dav.calls)
        self.cli("calendars")
        self.assertEqual(len(self.dav.calls) - n, 1)  # second run: only the home PROPFIND

    def test_kinds(self):
        rc, out, err = self.cli("calendars")
        rows = {r["name"]: r for r in tsv(out)}
        self.assertEqual(set(rows), {"Work", "Family", "Anna's Trip", "Work Trips", "Bob Schedule", "Holidays", "Reminders"})
        exp = {"Work": ("own", "rw", "me"), "Family": ("shared-by-me", "rw", "me"),
               "Anna's Trip": ("shared-with-me", "rw", "Anna Smith"), "Bob Schedule": ("shared-with-me", "ro", "Bob Jones"),
               "Holidays": ("subscribed", "ro", "example.com"), "Reminders": ("reminders", "rw", "me")}
        for name, (kind, access, owner) in exp.items():
            self.assertEqual((rows[name]["kind"], rows[name]["access"], rows[name]["owner"]), (kind, access, owner), name)
        self.assertEqual(rows["Family"]["sharees"], "2")
        self.assertEqual(rows["Work"]["color"], "#1BADF8")
        self.assertEqual(rows["Reminders"]["comps"], "VTODO")

    def test_json_extras(self):
        rc, out, err = self.cli("calendars", "-j")
        cals = {c["name"]: c for c in json.loads(out)}
        self.assertTrue(cals["Family"]["published"])
        self.assertEqual(cals["Holidays"]["source"], "webcal://example.com/holidays.ics")
        self.assertEqual([s["status"] for s in cals["Family"]["sharee_list"]], ["accepted", "noresponse"])

    def test_set_default_and_refuse_ro(self):
        rc, out, err = self.cli("calendars", "--set-default", "work")
        self.assertEqual(rc, 0, err)
        self.assertEqual(config.load("t")["default_calendar"], "work")
        rc, out, err = self.cli("calendars", "--set-default", "Bob Schedule")
        self.assertEqual(rc, 2)
        self.assertIn("read-only", err)


class TestCreateDeleteCalendar(Base):
    def test_create(self):
        rc, out, err = self.cli("calendars", "--create", "Gym & Sport", "--color", "#34c759")
        self.assertEqual(rc, 0, err)
        mk = self.dav.puts()[0]
        self.assertEqual(mk["method"], "MKCALENDAR")
        self.assertRegex(mk["url"], r"/1234567/calendars/[0-9A-F-]{36}/$")
        self.assertIn("<d:displayname>Gym &amp; Sport</d:displayname>", mk["body"])
        self.assertIn('<c:comp name="VEVENT"/>', mk["body"])
        self.assertIn("<a:calendar-color>#34C759FF</a:calendar-color>", mk["body"])
        row = tsv(out)[0]
        self.assertEqual((row["name"], row["kind"], row["access"], row["color"]), ("Gym & Sport", "own", "rw", "#34C759"))
        self.assertEqual(len(tsv(out)), 1)

    def test_create_refusals(self):
        for argv in (("--create", "work"), ("--create", "X", "--color", "red"), ("--color", "#000000"),
                     ("--create", "X", "--set-default", "Work")):
            rc, out, err = self.cli("calendars", *argv)
            self.assertEqual(rc, 2, argv)
        self.assertEqual(self.dav.puts(), [])

    def test_delete(self):
        self.cli("calendars", "--create", "Probe")
        cid = re.search(r"/calendars/([0-9A-F-]{36})/", self.dav.puts()[0]["url"]).group(1)
        path = f"{P}{cid}/"
        self.dav.add(path + "e.ics", SINGLE)
        rc, out, err = self.cli("calendars", "--delete", "Prob")  # substring is not enough
        self.assertEqual(rc, 2)
        rc, out, err = self.cli("calendars", "--delete", "probe")
        self.assertEqual(rc, 2)
        self.assertIn("--force", err)
        del self.dav.res[path + "e.ics"]
        rc, out, err = self.cli("calendars", "--delete", "probe")
        self.assertEqual(rc, 0, err)
        self.assertNotIn(path, self.dav.made)
        self.assertTrue(out.startswith("deleted\tProbe\t0\t"))

    def test_delete_only_own(self):
        for name in ("Family", "Anna's Trip", "Holidays", "Reminders"):
            rc, out, err = self.cli("calendars", "--delete", name)
            self.assertEqual(rc, 2, name)
        self.assertEqual(self.dav.puts(), [])


class TestAdd(Base):
    def put(self):
        puts = self.dav.puts()
        self.assertEqual(len(puts), 1)
        return puts[0]

    def test_add_timed(self):
        rc, out, err = self.cli("add", "--title", "Dentist", "--start", "2026-10-07 14:00", "--duration", "45m",
                                "--cal", "Work", "--alarm", "1h", "--location", "Clinic, 2nd floor")
        self.assertEqual(rc, 0, err)
        p = self.put()
        self.assertEqual(p["headers"]["If-None-Match"], "*")
        self.assertTrue(p["url"].startswith(HOME + "work/") and p["url"].endswith(".ics"))
        b = p["body"]
        self.assertIn("DTSTART;TZID=Europe/Lisbon:20261007T140000", b)
        self.assertIn("DTEND;TZID=Europe/Lisbon:20261007T144500", b)
        self.assertIn("BEGIN:VTIMEZONE", b)
        self.assertIn("BEGIN:DAYLIGHT", b)
        self.assertIn("TRIGGER:-PT1H", b)
        self.assertIn("LOCATION:Clinic\\, 2nd floor", b)
        self.assertTrue(p["headers"]["Content-Type"].startswith("text/calendar"))
        cols = out.strip().split("\t")
        self.assertEqual(cols[0], "added")
        self.assertEqual(cols[3:], ["2026-10-07 14:00", "2026-10-07 14:45", "Dentist"])

    def _add_alarms(self, *extra, start=None):
        import datetime as dt
        start = start or f"{(dt.date.today() + dt.timedelta(days=5)).isoformat()} 14:00"
        rc, out, err = self.cli("add", "--title", "A", "--start", start, "--cal", "Work", *extra)
        self.assertEqual(rc, 0, err)
        return re.findall(r"TRIGGER:(\S+)", self.put()["body"])

    def test_add_default_alarms(self):
        reset_profile(default_alarms=["1d", "1h"], default_alarms_today=["2h", "1h"])
        self.assertEqual(self._add_alarms(), ["-P1D", "-PT1H"])

    def test_add_default_alarms_today_drop_past(self):
        import datetime as dt
        reset_profile(default_alarms=["1d", "1h"], default_alarms_today=["2h", "1h"])
        now = dt.datetime.now()
        if now.hour >= 22:
            self.skipTest("needs an event later today")
        start = (now + dt.timedelta(minutes=90)).strftime("%Y-%m-%d %H:%M")
        self.assertEqual(self._add_alarms(start=start), ["-PT1H"])

    def test_add_explicit_or_no_alarm_overrides_default(self):
        reset_profile(default_alarms=["1d", "1h"])
        self.assertEqual(self._add_alarms("--alarm", "10m"), ["-PT10M"])

    def test_add_no_alarm(self):
        reset_profile(default_alarms=["1d", "1h"])
        self.assertEqual(self._add_alarms("--no-alarm"), [])

    def test_add_all_day_inclusive_end(self):
        rc, out, err = self.cli("add", "--title", "Trip", "--start", "2026-10-10", "--end", "2026-10-12",
                                "--all-day", "--cal", "work")
        self.assertEqual(rc, 0, err)
        b = self.put()["body"]
        self.assertIn("DTSTART;VALUE=DATE:20261010", b)
        self.assertIn("DTEND;VALUE=DATE:20261013", b)
        self.assertNotIn("VTIMEZONE", b)

    def test_date_without_time_needs_all_day(self):
        rc, out, err = self.cli("add", "--title", "X", "--start", "2026-10-10", "--cal", "Work")
        self.assertEqual(rc, 2)
        self.assertIn("--all-day", err)

    def test_refusals_per_kind(self):
        for cal, word in (("Bob Schedule", "read-only"), ("Holidays", "subscribed"), ("Reminders", "Reminders")):
            rc, out, err = self.cli("add", "--title", "X", "--start", "2026-10-10 10:00", "--cal", cal)
            self.assertEqual(rc, 2, cal)
            self.assertIn(word, err)
        self.assertEqual(self.dav.puts(), [])

    def test_shared_notes(self):
        rc, out, err = self.cli("add", "--title", "X", "--start", "2026-10-10 10:00", "--cal", "Family")
        self.assertEqual(rc, 0, err)
        self.assertIn("shared with 2 people", err)
        rc, out, err = self.cli("add", "--title", "X", "--start", "2026-10-10 10:00", "--cal", "Anna's Trip")
        self.assertEqual(rc, 0, err)
        self.assertIn("belongs to Anna Smith", err)
        self.assertTrue(self.dav.puts()[-1]["url"].startswith(HOME + "annas-trip/"))
        self.assertNotIn("ORGANIZER", self.dav.puts()[-1]["body"])

    def test_ambiguous_and_missing_calendar(self):
        rc, out, err = self.cli("add", "--title", "X", "--start", "2026-10-10 10:00", "--cal", "trip")
        self.assertEqual(rc, 2)
        self.assertIn("ambiguous", err)
        self.assertIn("annas-trip", err)
        self.assertIn("work-trips", err)
        rc, out, err = self.cli("add", "--title", "X", "--start", "2026-10-10 10:00", "--cal", "Nope")
        self.assertEqual(rc, 2)
        self.assertIn("no calendar 'Nope'", err)

    def test_default_calendar(self):
        rc, out, err = self.cli("add", "--title", "X", "--start", "2026-10-10 10:00")
        self.assertEqual(rc, 2)
        self.assertIn("which calendar", err)
        reset_profile(default_calendar="work-trips")
        rc, out, err = self.cli("add", "--title", "X", "--start", "2026-10-10 10:00")
        self.assertEqual(rc, 0, err)
        self.assertIn("/work-trips/", self.dav.puts()[-1]["url"])

    def test_dry_run_writes_nothing(self):
        rc, out, err = self.cli("add", "--title", "X", "--start", "2026-10-10 10:00", "--dry-run")
        self.assertEqual(rc, 0, err)
        self.assertIn("BEGIN:VEVENT", out)
        self.assertEqual(self.dav.puts(), [])


class TestList(Base):
    def test_local_expansion_exdate_override(self):
        self.dav.add(P + "work/WEEKLY-1.ics", WEEKLY)
        rc, out, err = self.cli("list", "--from", "2026-10-05", "--to", "2026-10-14", "-j")
        self.assertEqual(rc, 0, err)
        rows = json.loads(out)
        got = [(r["start"], r["title"]) for r in rows]
        self.assertEqual(got, [("2026-10-05 09:30", "Standup"), ("2026-10-12 11:00", "Standup (late)"),
                               ("2026-10-14 09:30", "Standup")])
        self.assertTrue(all(r["recurring"] for r in rows))
        self.assertEqual(rows[0]["expanded"], "local")
        report = [c for c in self.dav.calls if c["method"] == "REPORT"][0]
        self.assertIn("<c:expand", report["body"])
        self.assertIn('start="20261004T230000Z"', report["body"])  # Lisbon midnight in UTC (WEST)

    def test_dst_wall_time_kept(self):
        self.dav.add(P + "work/WEEKLY-1.ics", WEEKLY)
        rc, out, err = self.cli("list", "--from", "2026-10-26", "--to", "2026-10-26", "--fields", "start")
        self.assertEqual(out.strip().split("\n")[1], "2026-10-26 09:30")  # after the DST switch on Oct 25

    def test_server_expanded(self):
        self.dav.add(P + "work/SRV-1.ics", "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:SRV-1\r\nDTSTART:20261005T170000Z\r\n"
                     "RRULE:FREQ=DAILY\r\nSUMMARY:Gym\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
        self.dav.expanded[P + "work/SRV-1.ics"] = EXPANDED
        rc, out, err = self.cli("list", "--from", "2026-10-05", "--days", "2", "-j", "--cal", "Work")
        rows = json.loads(out)
        self.assertEqual([r["start"] for r in rows], ["2026-10-05 18:00", "2026-10-06 18:00"])
        self.assertEqual({r["expanded"] for r in rows}, {"server"})
        self.assertTrue(rows[0]["recurring"])

    def test_subscribed_feed_gets_no_credentials(self):
        self.dav.feeds["https://example.com/holidays.ics"] = FEED
        rc, out, err = self.cli("list", "--from", "2027-10-01", "--days", "10", "--cal", "Holidays")
        self.assertEqual(rc, 0, err)
        rows = tsv(out)
        self.assertEqual((rows[0]["start"], rows[0]["end"], rows[0]["title"]), ("2027-10-05", "2027-10-05", "Republic Day"))
        feed = [c for c in self.dav.calls if c["url"].startswith("https://example.com")][0]
        self.assertNotIn("Authorization", feed["headers"])

    def test_broken_feed_is_a_note(self):
        rc, out, err = self.cli("list", "--from", "2026-10-05")
        self.assertEqual(rc, 0, err)
        self.assertIn("Holidays: feed not readable", err)

    def test_reminders_never_queried_and_grep(self):
        self.dav.add(P + "work/SINGLE.ics", SINGLE)
        rc, out, err = self.cli("list", "--from", "2026-10-06", "--days", "1", "--grep", "bob")
        rows = tsv(out)
        self.assertEqual([r["title"] for r in rows], ["Lunch, with Bob"])
        urls = [c["url"] for c in self.dav.calls if c["method"] == "REPORT"]
        self.assertFalse(any("/tasks/" in u for u in urls))


class TestShowEditDelete(Base):
    def setUp(self):
        super().setUp()
        self.dav.add(P + "work/SINGLE.ics", SINGLE, etag='"v1"')
        self.dav.add(P + "work/WEEKLY-1.ics", WEEKLY, etag='"w1"')
        self.dav.add(P + "bob-ro/RO-1.ics", SINGLE.replace("SINGLE-ABCDEF", "RO-123456"), etag='"r1"')

    def test_show(self):
        rc, out, err = self.cli("show", "WEEKLY-1")
        self.assertEqual(rc, 0, err)
        self.assertIn("# Standup", out)
        self.assertIn("alarms: 15m before", out)
        self.assertIn("repeat: FREQ=WEEKLY;BYDAY=MO,WE", out)
        self.assertIn("calendar: Work (own, rw)", out)
        rc, out, err = self.cli("show", "SINGLE-AB", "-j")  # unique prefix
        d = json.loads(out)
        self.assertEqual(d["notes"], "line1\nline2")
        self.assertIn("X-KEEP-ME", d["ics"])

    def test_show_missing(self):
        rc, out, err = self.cli("show", "NOPE-NOPE")
        self.assertEqual(rc, 2)
        self.assertIn("no event", err)

    def test_edit_keeps_unknown_and_duration(self):
        rc, out, err = self.cli("edit", "SINGLE-ABCDEF", "--start", "2026-10-07 15:00", "--title", "Lunch moved")
        self.assertEqual(rc, 0, err)
        p = self.dav.puts()[0]
        self.assertEqual(p["headers"]["If-Match"], '"v1"')
        b = p["body"]
        self.assertIn("X-KEEP-ME;X-P=1:yes", b)
        self.assertIn("DTSTART;TZID=Europe/Lisbon:20261007T150000", b)
        self.assertIn("DTEND;TZID=Europe/Lisbon:20261007T160000", b)
        self.assertIn("SEQUENCE:1", b)
        self.assertIn("SUMMARY:Lunch moved", b)
        self.assertIn("DESCRIPTION:line1\\nline2", b)

    def test_edit_series_note_and_alarms(self):
        rc, out, err = self.cli("edit", "WEEKLY-1", "--no-alarms")
        self.assertEqual(rc, 0, err)
        self.assertIn("whole series", err)
        b = self.dav.puts()[0]["body"]
        self.assertNotIn("VALARM", b)
        self.assertIn("RECURRENCE-ID", b)  # override kept
        self.assertIn("SEQUENCE:3", b)

    def test_edit_412(self):
        self.dav.res[P + "work/SINGLE.ics"] = ('"v2"', SINGLE)
        with mock.patch("src.api.events.find") as f:
            from src.api import ics
            f.return_value = {"cal": {"name": "Work", "kind": "own", "access": "rw", "events": True, "id": "work",
                                      "href": HOME + "work/"}, "href": HOME + "work/SINGLE.ics", "etag": '"v1"',
                              "ics": SINGLE, "vcal": ics.parse(SINGLE), "uid": "SINGLE-ABCDEF"}
            rc, out, err = self.cli("edit", "SINGLE-ABCDEF", "--title", "x")
        self.assertEqual(rc, 1)
        self.assertIn("412", err)
        self.assertIn("rerun", err)

    def test_edit_nothing(self):
        rc, out, err = self.cli("edit", "SINGLE-ABCDEF")
        self.assertEqual(rc, 2)

    def test_readonly_refused(self):
        for cmd in (("edit", "RO-123456", "--title", "x"), ("delete", "RO-123456")):
            rc, out, err = self.cli(*cmd)
            self.assertEqual(rc, 2, cmd)
            self.assertIn("read-only", err)
        self.assertEqual(self.dav.puts(), [])

    def test_delete(self):
        rc, out, err = self.cli("delete", "SINGLE-ABCDEF", "--dry-run")
        self.assertEqual(self.dav.puts(), [])
        rc, out, err = self.cli("delete", "SINGLE-ABCDEF")
        self.assertEqual(rc, 0, err)
        d = self.dav.puts()[0]
        self.assertEqual((d["method"], d["headers"]["If-Match"]), ("DELETE", '"v1"'))
        self.assertNotIn(P + "work/SINGLE.ics", self.dav.res)


class TestAuthAndOnboard(Base):
    def test_401_no_password_leak(self):
        self.dav.fail[("PROPFIND", "/")] = 401
        rc, out, err = self.cli("calendars")
        self.assertEqual(rc, 2)
        self.assertIn("401", err)
        self.assertNotIn(PASSWORD, out + err)

    def test_onboard_steps(self):
        import shutil
        from support import TMP
        shutil.rmtree(f"{TMP}/root/new", ignore_errors=True)
        env = {k: v for k, v in os.environ.items() if not k.startswith("ICLOUD_")}
        with mock.patch.dict(os.environ, env, clear=True):
            rc, out, err = self.cli("onboard", "--profile", "new")
            self.assertEqual(rc, 5)
            self.assertIn("WAITING apple-id", out)
            rc, out, err = self.cli("onboard", "--profile", "new", "--apple-id", "me@icloud.com")
            self.assertEqual(rc, 5)
            self.assertIn("WAITING app-password", out)
            self.assertIn("App-Specific Passwords", out)
            self.assertIn("ICLOUD_APP_PASSWORD", out)
        with mock.patch.dict(os.environ, {**env, "ICLOUD_APP_PASSWORD": "bad"}, clear=True):
            self.dav.fail[("PROPFIND", "/")] = 401
            rc, out, err = self.cli("onboard", "--profile", "new")
            self.assertEqual(rc, 5)
            self.assertIn("WAITING password-rejected", out)
            del self.dav.fail[("PROPFIND", "/")]
            rc, out, err = self.cli("onboard", "--profile", "new")
        self.assertEqual(rc, 0, err)
        self.assertIn("DONE profile new", out)
        self.assertIn("Which calendar", out)
        self.assertEqual(config.load("new")["home"], HOME)
        shutil.rmtree(f"{TMP}/root/new")

    def test_profiles_never_show_password(self):
        rc, out, err = self.cli("profiles")
        self.assertEqual(rc, 0, err)
        self.assertIn("\tset\t", out)
        self.assertNotIn(PASSWORD, out + err)

    def test_invites(self):
        rc, out, err = self.cli("invites")
        self.assertEqual(rc, 0, err)
        rows = tsv(out)
        self.assertEqual(rows, [{"calendar": "Chess Club", "from": "Carol", "access": "ro", "status": "noresponse",
                                 "uid": "inv-42"}])


class TestRails(unittest.TestCase):
    def test_commands_never_mutate_or_speak_http(self):
        r = subprocess.run(["grep", "-rnE", "allow_mutate|http\\.request|\\.mutate\\(", "src/commands"],
                           cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(r.stdout, "")

    def test_http_rail(self):
        from src.core import http
        with self.assertRaises(RuntimeError):
            http.request("PUT", "https://p1-caldav.icloud.com/x")
        self.assertTrue(http.trusted("https://p42-caldav.icloud.com:443/1/"))
        self.assertFalse(http.trusted("https://icloud.com.evil.example/"))
        self.assertFalse(http.trusted("http://caldav.icloud.com/"))


if __name__ == "__main__":
    unittest.main()
