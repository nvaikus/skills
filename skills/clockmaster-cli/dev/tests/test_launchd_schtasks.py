"""launchd + Task Scheduler backends with the OS tools mocked: plist / XML
content, drift, sync verbs, TCC warnings, the Windows date guard."""
import plistlib
import re
from datetime import datetime
from unittest import mock

import base
import ops
import taskdef
from errors import ValidationError
from backends import launchd, schtasks


class FakeLaunchctl:
    def __init__(self):
        self.calls, self.loaded = [], set()

    def __call__(self, *args):
        self.calls.append(args)
        verb, target = args[0], args[-1]
        if verb == "print":
            lbl = target.split("/")[-1]
            return base.Proc(0 if lbl in self.loaded else 113, "\tpid = 777\n" if lbl in self.loaded else "")
        if verb == "bootstrap":
            with open(target, "rb") as fh:
                self.loaded.add(plistlib.load(fh)["Label"])
        if verb == "bootout":
            self.loaded.discard(target.split("/")[-1])
        return base.Proc()


class Launchd(base.Case):
    scheduler = "launchd"

    def setUp(self):
        super().setUp()
        self.lc = FakeLaunchctl()
        p = mock.patch.object(launchd, "launchctl", self.lc)
        p.start()
        self.addCleanup(p.stop)

    def test_plist(self):
        t = taskdef.from_text("rep", 'schedule: "0 9 * * 1-5"\ncommand: x\n')
        d = plistlib.loads(launchd.plist_bytes(t))
        self.assertEqual(d["Label"], "com.claude.clockmaster.rep")
        self.assertEqual(d["ProgramArguments"][:2], ["/bin/zsh", "-lic"])
        self.assertEqual(d["ProgramArguments"][2], f"exec '{base.identity.ENTRY}' _exec 'rep'")
        self.assertEqual(d["EnvironmentVariables"], {"TERM": "dumb", "CLOCKMASTER_HOME": str(self.tmp / "data")})
        self.assertEqual(len(d["StartCalendarInterval"]), 5)
        self.assertTrue(d["StandardOutPath"].endswith("launchd-io/rep.log"))

    def test_sync_and_states(self):
        self.write_task("a", 'schedule: "0 9 * * *"\ncommand: x\n')
        self.write_task("off", 'schedule: "0 9 * * *"\ncommand: x\nenabled: false\n')
        agents = self.tmp / "home" / "Library" / "LaunchAgents"
        agents.mkdir(parents=True)
        (agents / "com.claude.clockmaster.gone.plist").write_bytes(b"x")
        (agents / "com.claude.clockmaster-ui.plist").write_bytes(b"ui")
        ok, lines = ops.sync()
        self.assertTrue(ok, lines)
        self.assertTrue(lines[0].startswith("~ a: scheduled '0 9 * * *' (every day at 9:00; 1 interval)"))
        self.assertIn("- gone: removed from launchd", lines)
        self.assertTrue((agents / "com.claude.clockmaster-ui.plist").exists())
        self.assertEqual(launchd.states(taskdef.load_all()), {"a": "ok", "off": "off"})
        self.lc.loaded.clear()
        self.assertEqual(launchd.state(taskdef.load("a")), "unloaded")
        ok, lines = ops.sync()
        self.assertIn("+ a: loaded", lines)
        self.write_task("a", 'schedule: "0 8 * * *"\ncommand: x\n')
        self.assertEqual(launchd.state(taskdef.load("a")), "stale")

    def test_tcc_warning_follows_symlinks(self):
        real = self.tmp / "icloud" / "Documents"
        (real / "proj").mkdir(parents=True)
        (self.tmp / "home" / "Documents").symlink_to(real)
        t = taskdef.from_text("a", f'schedule: "0 9 * * *"\ncommand: x\nworkdir: {real}/proj\n')
        w = launchd.tcc_warnings([t])
        self.assertEqual(len(w), 1)
        self.assertIn("~/Documents", w[0])
        t2 = taskdef.from_text("b", 'schedule: "0 9 * * *"\ncommand: ~/Desktop/run.sh\n')
        self.assertIn("command path", launchd.tcc_warnings([t2])[0])
        t3 = taskdef.from_text("c", 'schedule: "0 9 * * *"\ncommand: echo ~/Documents\n')
        self.assertEqual(launchd.tcc_warnings([t3]), [])

    def test_ui_agent(self):
        d = plistlib.loads(launchd.ui_plist_bytes(7788))
        self.assertEqual(d["Label"], "com.claude.clockmaster-ui")
        self.assertTrue(d["KeepAlive"])
        self.assertEqual(d["ProgramArguments"][2:], ["ui", "--fg"])
        launchd.ui_autostart_on(7790)
        st = launchd.ui_autostart_state()
        self.assertEqual((st["port"], st["pid"]), (7790, 777))
        launchd.ui_autostart_restart(7790)
        self.assertEqual(self.lc.calls[-1][:2], ("kickstart", "-k"))
        launchd.ui_autostart_off()
        self.assertIsNone(launchd.ui_autostart_state())


class FakeSchtasks:
    def __init__(self):
        self.tasks, self.calls = {}, []

    def __call__(self, *args, binary=False):
        self.calls.append(args)
        if args[0] == "/create":
            with open(args[4], "rb") as fh:
                self.tasks[args[2]] = fh.read().decode("utf-16")
            return base.Proc()
        if args[0] == "/delete":
            return base.Proc(0 if self.tasks.pop(args[2], None) else 1)
        if args[0] == "/query" and "/xml" in args:
            x = self.tasks.get(args[2])
            return base.Proc(1, b"") if x is None else base.Proc(0, x.encode())
        if args[0] == "/query":
            rows = [f'"{tn}","N/A","Ready"' for tn in self.tasks]
            return base.Proc(0 if rows else 1, "\n".join(rows))
        return base.Proc()


class Schtasks(base.Case):
    scheduler = "schtasks"

    def setUp(self):
        super().setUp()
        self.st = FakeSchtasks()
        p = mock.patch.object(schtasks, "schtasks", self.st)
        p.start()
        self.addCleanup(p.stop)

    def test_triggers(self):
        c = taskdef.from_text("a", 'schedule: "*/10 * * * *"\ncommand: x\n').cron
        self.assertEqual(schtasks.trigger_times(c), ([(0, 0)], 10))
        c = taskdef.from_text("a", 'schedule: "0,30 9 * * *"\ncommand: x\n').cron
        self.assertEqual(schtasks.trigger_times(c), ([(9, 0), (9, 30)], None))
        c = taskdef.from_text("a", 'schedule: "*/7 * * * *"\ncommand: x\n').cron  # not a whole-hour grid
        self.assertEqual(len(schtasks.trigger_times(c)[0]), 24 * 9)
        with self.assertRaises(ValidationError):
            schtasks.trigger_times(taskdef.from_text("a", 'schedule: "* 0-9 * * *"\ncommand: x\n').cron)

    def test_xml(self):
        t = taskdef.from_text("a", 'schedule: "0 9 13 * 5"\ncommand: x\n')
        x = schtasks.task_xml(t)
        self.assertIn("<URI>\\clockmaster\\a</URI>", x)
        self.assertIn("<StartBoundary>2000-01-01T09:00:00</StartBoundary>", x)
        self.assertIn("<DaysOfMonth><Day>13</Day></DaysOfMonth>", x)  # weekday dropped -> exec_guard
        self.assertIn("<StartWhenAvailable>true</StartWhenAvailable>", x)
        self.assertIn("<ExecutionTimeLimit>PT0S</ExecutionTimeLimit>", x)
        self.assertTrue(schtasks.xml_bytes(t).startswith(b"\xff\xfe"))
        self.assertTrue(schtasks.exec_guard(t, datetime(2026, 11, 13, 9, 3)))
        self.assertFalse(schtasks.exec_guard(t, datetime(2026, 10, 13, 9, 0)))
        w = taskdef.from_text("w", 'schedule: "0 9 * * 1,3"\ncommand: x\n')
        self.assertIn("<DaysOfWeek><Monday /><Wednesday /></DaysOfWeek>", schtasks.task_xml(w))

    def test_sync(self):
        self.write_task("a", 'schedule: "0 9 * * *"\ncommand: x\n')
        self.st.tasks["\\clockmaster\\gone"] = "<Task/>"
        ok, lines = ops.sync()
        self.assertTrue(ok, lines)
        self.assertIn("~ a: scheduled '0 9 * * *' (1 trigger)", lines)
        self.assertIn("- gone: removed from Task Scheduler", lines)
        self.assertEqual(schtasks.state(taskdef.load("a")), "ok")
        self.st.tasks["\\clockmaster\\a"] = re.sub(
            r"(<AllowStartOnDemand>true</AllowStartOnDemand>\s*)<Enabled>true", r"\1<Enabled>false",
            self.st.tasks["\\clockmaster\\a"])
        self.assertEqual(schtasks.state(taskdef.load("a")), "unloaded")
        ok, lines = ops.sync()
        self.assertIn("+ a: re-enabled", lines)
        ops.remove("a")
        self.assertEqual(self.st.tasks, {})
        self.assertFalse(list((self.tmp / "data" / "schtasks-xml").glob("*.xml")))


if __name__ == "__main__":
    import unittest
    unittest.main()
