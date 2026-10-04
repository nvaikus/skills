import shutil
import subprocess
import unittest
from datetime import datetime

import base  # noqa: F401
import cron
from errors import ValidationError


class Parse(unittest.TestCase):
    def test_fields(self):
        c = cron.Cron("*/15 9-17 * * 1-5")
        self.assertEqual(c.minute, [0, 15, 30, 45])
        self.assertEqual(c.hour, list(range(9, 18)))
        self.assertIsNone(c.day)
        self.assertEqual(c.weekday, [1, 2, 3, 4, 5])

    def test_sunday_7_and_full_week(self):
        self.assertEqual(cron.Cron("0 0 * * 7").weekday, [0])
        self.assertIsNone(cron.Cron("0 0 * * 0-6").weekday)

    def test_bad(self):
        for bad in ("* * * *", "60 * * * *", "* 24 * * *", "x * * * *", "*/0 * * * *"):
            with self.assertRaises(ValidationError, msg=bad):
                cron.Cron(bad)


class Match(unittest.TestCase):
    def test_day_and_weekday_are_anded(self):
        c = cron.Cron("0 9 13 * 5")  # Friday the 13th only
        self.assertTrue(c.matches(datetime(2026, 11, 13, 9, 0)))   # Fri 13
        self.assertFalse(c.matches(datetime(2026, 10, 13, 9, 0)))  # Tue 13
        self.assertFalse(c.matches(datetime(2026, 10, 16, 9, 0)))  # Fri 16

    def test_next_after(self):
        c = cron.Cron("30 8 * * 1")
        self.assertEqual(c.next_after(datetime(2026, 10, 2, 12, 0)), datetime(2026, 10, 5, 8, 30))
        self.assertEqual(cron.Cron("0 0 29 2 *").next_after(datetime(2026, 1, 1)), datetime(2028, 2, 29, 0, 0))
        self.assertIsNone(cron.Cron("0 0 29 2 1").next_after(datetime(2026, 1, 1)))  # 2044: past the 5-year scan

    def test_walk_window(self):
        got = list(cron.Cron("0 */6 * * *").walk(datetime(2026, 10, 2, 0, 0), datetime(2026, 10, 2, 23, 59)))
        self.assertEqual([d.hour for d in got], [0, 6, 12, 18])


class Describe(unittest.TestCase):
    def test_stepped_hours(self):
        self.assertEqual(cron.describe("0 */4 * * *"), "every 4 hours")
        self.assertEqual(cron.describe("0 6-22/2 * * 1-5"), "every 2 hours from 6:00 to 22:00 on weekdays")
        self.assertEqual(cron.describe("0 8-20 * * *"), "every hour from 8:00 to 20:00")
        self.assertEqual(cron.describe("0 0,12 * * *"), "every day at 0:00 and 12:00")

    CASES = {
        "0 9 * * 1-5": "every weekday at 9:00",
        "*/15 * * * *": "every 15 minutes",
        "* * * * *": "every minute",
        "30 8 * * *": "every day at 8:30",
    }

    def test_known_phrases(self):
        for expr, want in self.CASES.items():
            self.assertEqual(cron.describe(expr), want, expr)

    def test_every_case_reads_as_words(self):
        for expr in ("*/5 9-17 * * 1-5", "0 0 1 * *", "0 12 * 6-8 *", "0 9 13 * 5", "15 14 1,15 * *",
                     "0 22 * * 0,6", "0 * * * *", "5 4 * * 0", "0 0,12 * * *"):
            text = cron.describe(expr)
            self.assertNotEqual(text, expr)
            self.assertNotIn("*", text, expr)

    def test_and_semantics_in_words(self):
        self.assertIn("if it is a Friday", cron.describe("0 9 13 * 5"))

    def test_unparsable_passes_through(self):
        self.assertEqual(cron.describe("nonsense"), "nonsense")


class Upcoming(unittest.TestCase):
    def test_upcoming(self):
        got = cron.upcoming("0 9 * * 1-5", 3, now=datetime(2026, 10, 2, 10, 0))  # Friday
        self.assertEqual(got, [datetime(2026, 10, 5, 9), datetime(2026, 10, 6, 9), datetime(2026, 10, 7, 9)])
        self.assertEqual(cron.upcoming("0 0 30 2 *", 3), [])


class Backends(unittest.TestCase):
    def test_calendar_intervals(self):
        iv = cron.calendar_intervals(cron.Cron("0 9 * * 1-5"))
        self.assertEqual(len(iv), 5)
        self.assertEqual(iv[0], {"Weekday": 1, "Hour": 9, "Minute": 0})
        self.assertEqual(cron.calendar_intervals(cron.Cron("* * * * *")), [{}])
        with self.assertRaises(ValidationError):
            cron.calendar_intervals(cron.Cron("*/2 * 1-20 * *"))

    def test_oncalendar_text(self):
        self.assertEqual(cron.oncalendar(cron.Cron("*/15 9-10 * * 1-5")),
                         "Mon,Tue,Wed,Thu,Fri *-*-* 09,10:00,15,30,45:00")

    @unittest.skipUnless(shutil.which("systemd-analyze"), "systemd-analyze not installed")
    def test_oncalendar_agrees_with_systemd(self):
        """systemd's own parser accepts every OnCalendar we emit, and its next
        elapse equals cron.next_after (both in local time)."""
        for expr in ("*/15 9-17 * * 1-5", "0 9 13 * 5", "30 8 * * *", "0 0 1 1,7 *", "* * * * *",
                     "5 4 * * 0", "0 12 29 2 *", "0 0,12 * 6-8 6,0"):
            c = cron.Cron(expr)
            r = subprocess.run(["systemd-analyze", "calendar", "--iterations=3", cron.oncalendar(c)],
                               capture_output=True, text=True, timeout=10)
            self.assertEqual(r.returncode, 0, f"{expr}: {r.stderr}")
            stamps = [ln.split(":", 1)[1].strip() for ln in r.stdout.splitlines()
                      if ln.strip().startswith(("Next elapse:", "Iteration #"))]
            ours, now = [], datetime.now()
            for _ in range(3):
                now = c.next_after(now)
                ours.append(now.strftime("%Y-%m-%d %H:%M:%S"))
            got = [" ".join(s.split()[1:3]) for s in stamps[:3]]
            self.assertEqual(got, ours, expr)


if __name__ == "__main__":
    unittest.main()
