"""Unit tests: recurrence, iCalendar text, VTIMEZONE, time parsing, invites."""
import datetime as dt
import unittest
from zoneinfo import ZoneInfo

import support  # noqa: F401  (env + sys.path)

from src.api import ics, invites, recur, when  # noqa: E402

LIS = ZoneInfo("Europe/Lisbon")
UTC = dt.timezone.utc


def occ(start, rule, until, **kw):
    return recur.occurrences(start, rule, until, **kw)


class TestRecur(unittest.TestCase):
    def test_monthly_last_friday(self):
        got = occ(dt.date(2026, 1, 30), "FREQ=MONTHLY;BYDAY=-1FR;COUNT=4", dt.date(2027, 1, 1))
        self.assertEqual(got, [dt.date(2026, 1, 30), dt.date(2026, 2, 27), dt.date(2026, 3, 27), dt.date(2026, 4, 24)])

    def test_until_inclusive_and_interval(self):
        s = dt.datetime(2026, 10, 1, 9, tzinfo=LIS)
        got = occ(s, "FREQ=DAILY;INTERVAL=2;UNTIL=20261007T080000Z", dt.datetime(2027, 1, 1, tzinfo=UTC))
        self.assertEqual([t.day for t in got], [1, 3, 5, 7])

    def test_dst_keeps_wall_time(self):
        s = dt.datetime(2026, 10, 24, 9, tzinfo=LIS)
        got = occ(s, "FREQ=DAILY;COUNT=3", dt.datetime(2027, 1, 1, tzinfo=UTC))
        self.assertEqual([t.hour for t in got], [9, 9, 9])
        self.assertEqual([t.utcoffset().seconds // 3600 for t in got], [1, 0, 0])

    def test_exdate_and_bymonthday(self):
        got = occ(dt.date(2026, 1, 31), "FREQ=MONTHLY;BYMONTHDAY=31;COUNT=3", dt.date(2027, 1, 1),
                  exdates=[dt.date(2026, 3, 31)])
        self.assertEqual(got, [dt.date(2026, 1, 31), dt.date(2026, 5, 31)])  # COUNT counts the exdate too

    def test_yearly_bysetpos(self):
        got = occ(dt.date(2026, 11, 26), "FREQ=YEARLY;BYMONTH=11;BYDAY=TH;BYSETPOS=4;COUNT=2", dt.date(2030, 1, 1))
        self.assertEqual(got, [dt.date(2026, 11, 26), dt.date(2027, 11, 25)])

    def test_unsupported(self):
        with self.assertRaises(recur.Unsupported):
            occ(dt.date(2026, 1, 1), "FREQ=DAILY;BYHOUR=9,17", dt.date(2027, 1, 1))


class TestIcs(unittest.TestCase):
    def test_fold_roundtrip_utf8(self):
        c = ics.Component("VCALENDAR", subs=[ics.Component("VEVENT")])
        long = "Встреча; с командой, " * 10 + "\nend"
        c.subs[0].set_text("SUMMARY", long)
        text = ics.to_text(c)
        for line in text.split("\r\n"):
            self.assertLessEqual(len(line.encode()), 75)
        self.assertEqual(ics.parse(text).components("VEVENT")[0].text("SUMMARY"), long)

    def test_quoted_params_and_unknown_kept(self):
        src = 'BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nX-APPLE-STRUCTURED-LOCATION;VALUE=URI;X-TITLE="A:B;C":geo:1,2\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n'
        p = ics.parse(src).components("VEVENT")[0].get("X-APPLE-STRUCTURED-LOCATION")
        self.assertEqual((p.params["X-TITLE"], p.value), ("A:B;C", "geo:1,2"))
        self.assertIn('X-TITLE="A:B;C":geo:1,2', ics.to_text(ics.parse(src)))

    def test_durations(self):
        self.assertEqual(ics.parse_duration("-PT15M"), -dt.timedelta(minutes=15))
        self.assertEqual(ics.fmt_duration(dt.timedelta(days=1, hours=2)), "P1DT2H")
        self.assertEqual(ics.fmt_duration(dt.timedelta(0)), "PT0S")

    def test_vtimezone_lisbon(self):
        vt = ics.vtimezone("Europe/Lisbon", 2026)
        kinds = [c.name for c in vt.subs]
        self.assertIn("DAYLIGHT", kinds)
        self.assertIn("STANDARD", kinds)
        day = [c for c in vt.subs if c.name == "DAYLIGHT" and c.value("DTSTART").startswith("2026")][0]
        self.assertEqual((day.value("DTSTART"), day.value("TZOFFSETFROM"), day.value("TZOFFSETTO")),
                         ("20260329T010000", "+0000", "+0100"))

    def test_vtimezone_no_dst(self):
        vt = ics.vtimezone("Asia/Tokyo", 2026)
        self.assertEqual([c.name for c in vt.subs], ["STANDARD"])
        self.assertEqual(vt.subs[0].value("TZOFFSETTO"), "+0900")


class TestWhen(unittest.TestCase):
    def test_forms(self):
        self.assertEqual(when.point("2026-10-07", LIS), (dt.date(2026, 10, 7), None))
        t, _ = when.point("2026-10-07 14:30", LIS)
        self.assertEqual((t.hour, t.minute, t.tzinfo), (14, 30, LIS))
        t, _ = when.point("2026-10-07T14:30:00Z", LIS)
        self.assertEqual(t.utcoffset(), dt.timedelta(0))
        t, _ = when.point("16:00", LIS, day=dt.date(2026, 10, 7))
        self.assertEqual((t.date(), t.hour), (dt.date(2026, 10, 7), 16))
        self.assertEqual(when.point("tomorrow", LIS)[0], when.today() + dt.timedelta(days=1))
        d = when.point("fri", LIS)[0]
        self.assertEqual(d.weekday(), 4)
        with self.assertRaises(Exception):
            when.point("month", LIS)

    def test_durations(self):
        self.assertEqual(when.duration("1h30m"), dt.timedelta(minutes=90))
        self.assertEqual(when.duration("45"), dt.timedelta(minutes=45))
        self.assertEqual(when.alarm("1d"), -dt.timedelta(days=1))


class TestInvites(unittest.TestCase):
    def test_parse(self):
        got = invites.parse(support.fixture("invite.xml"))
        self.assertEqual((got["calendar"], got["from"], got["access"], got["status"], got["uid"]),
                         ("Chess Club", "Carol", "ro", "noresponse", "inv-42"))


if __name__ == "__main__":
    unittest.main()
