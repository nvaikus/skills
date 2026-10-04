"""systemd backend against a fake `systemctl` on PATH (never the real manager)."""
import os

import base
import ops
import taskdef
from backends import systemd

FAKE = r'''
echo "$*" >> "$FAKE_LOG"
[ "$1" = "--user" ] && shift
case "$1" in
  show-environment) [ -e "$FAKE_DIR/nobus" ] && { echo "Failed to connect to bus: No medium found" >&2; exit 1; }; echo LANG=C ;;
  is-enabled) shift; for u in "$@"; do if [ -e "$FAKE_DIR/off" ]; then echo disabled; else echo enabled; fi; done ;;
  is-active) shift; for u in "$@"; do echo active; done ;;
  show) echo 4242 ;;
esac
exit 0
'''


class Systemd(base.Case):
    scheduler = "systemd"

    def setUp(self):
        super().setUp()
        os.environ["FAKE_LOG"] = str(self.tmp / "calls.log")
        os.environ["FAKE_DIR"] = str(self.tmp)
        self.fake_bin("systemctl", FAKE)
        self.fake_bin("loginctl", "echo Linger=no\n")
        self.units = self.tmp / "home" / ".config" / "systemd" / "user"

    def tearDown(self):
        os.environ.pop("FAKE_LOG", None)
        os.environ.pop("FAKE_DIR", None)
        super().tearDown()

    def calls(self):
        p = self.tmp / "calls.log"
        return p.read_text().splitlines() if p.exists() else []

    def test_unit_text(self):
        t = taskdef.from_text("rep", 'schedule: "*/15 9-17 * * 1-5"\ncommand: x\n')
        svc, tim = systemd.service_text(t), systemd.timer_text(t)
        for line in ("Type=oneshot", "TimeoutStartSec=infinity", f"Environment=\"CLOCKMASTER_HOME={self.tmp}/data\""):
            self.assertIn(line, svc)
        self.assertIn(f'ExecStart="{base.sys.executable}" "{base.identity.ENTRY}" "_exec" "rep"', svc)
        for line in ("OnCalendar=Mon,Tue,Wed,Thu,Fri *-*-* 09,10,11,12,13,14,15,16,17:00,15,30,45:00",
                     "Persistent=true", "AccuracySec=1s", "Unit=clockmaster.rep.service", "WantedBy=timers.target"):
            self.assertIn(line, tim)

    def test_catchup_false_not_persistent(self):
        t = taskdef.from_text("rep", 'schedule: "0 21 * * *"\ncommand: x\ncatchup: false\n')
        self.assertIn("Persistent=false", systemd.timer_text(t))

    def test_arg_escaping(self):
        self.assertEqual(systemd._arg('a "b" 50% $HOME\\x'), '"a \\"b\\" 50%% $$HOME\\\\x"')

    def test_sync_lifecycle(self):
        self.write_task("a", 'schedule: "0 9 * * *"\ncommand: x\n')
        self.write_task("b", 'schedule: "0 10 * * *"\ncommand: x\nenabled: false\n')
        (self.units).mkdir(parents=True)
        (self.units / "clockmaster.orphan.timer").write_text("x")
        (self.units / "clockmaster.orphan.service").write_text("x")
        (self.units / "clockmaster-ui.service").write_text("ui")  # outside the prefix: kept
        (self.units / "other.timer").write_text("x")
        ok, lines = ops.sync()
        self.assertTrue(ok, lines)
        self.assertTrue((self.units / "clockmaster.a.timer").exists())
        self.assertFalse((self.units / "clockmaster.b.timer").exists())
        self.assertFalse((self.units / "clockmaster.orphan.timer").exists())
        self.assertFalse((self.units / "clockmaster.orphan.service").exists())
        self.assertTrue((self.units / "clockmaster-ui.service").exists())
        self.assertTrue((self.units / "other.timer").exists())
        calls = self.calls()
        self.assertIn("--user daemon-reload", calls)
        self.assertIn("--user enable clockmaster.a.timer", calls)
        self.assertIn("--user restart clockmaster.a.timer", calls)
        self.assertIn("--user disable --now clockmaster.orphan.timer", calls)
        self.assertFalse([c for c in calls if "stop" in c.split() and "service" in c])  # runs are never killed
        self.assertTrue(any(l.startswith("~ a: scheduled '0 9 * * *' (every day at 9:00)") for l in lines))
        self.assertTrue(any("linger is off" in l for l in lines))
        self.assertEqual(systemd.states(taskdef.load_all()), {"a": "ok", "b": "off"})

        # second sync: nothing to do, no reload
        (self.tmp / "calls.log").unlink()
        ok, lines = ops.sync()
        self.assertIn("sync done: 1 scheduled, 0 changed, 1 unchanged", lines)
        self.assertNotIn("--user daemon-reload", self.calls())

    def test_drift_states(self):
        self.write_task("a", 'schedule: "0 9 * * *"\ncommand: x\n')
        ops.sync()
        t = taskdef.load("a")
        self.assertEqual(systemd.state(t), "ok")
        (self.tmp / "off").write_text("")
        self.assertEqual(systemd.state(t), "unloaded")
        os.remove(self.tmp / "off")
        self.write_task("a", 'schedule: "0 10 * * *"\ncommand: x\n')
        self.assertEqual(systemd.state(taskdef.load("a")), "stale")
        for p in self.units.glob("clockmaster.a.*"):
            p.unlink()
        self.assertEqual(systemd.state(taskdef.load("a")), "missing")

    def test_no_bus_is_a_clear_error(self):
        (self.tmp / "nobus").write_text("")
        self.write_task("a", 'schedule: "0 9 * * *"\ncommand: x\n')
        ok, lines = ops.sync()
        self.assertFalse(ok)
        self.assertIn("cannot reach the systemd user manager", lines[0])
        self.assertIn("crontab", lines[0])
        self.assertFalse((self.units / "clockmaster.a.timer").exists())
        self.assertIn("unreachable", systemd.notes()[0])

    def test_unregister_keeps_running_service(self):
        self.write_task("a", 'schedule: "0 9 * * *"\ncommand: x\n')
        ops.sync()
        ops.remove("a")
        self.assertFalse(list(self.units.glob("clockmaster.a.*")))
        self.assertIn("--user disable --now clockmaster.a.timer", self.calls())

    def test_ui_unit(self):
        text = systemd.ui_unit_text(7799)
        for line in ("Restart=always", "KillMode=process", "WantedBy=default.target", '"ui" "--fg" "--port" "7799"'):
            self.assertIn(line, text)
        self.assertIsNone(systemd.ui_autostart_state())
        self.units.mkdir(parents=True)
        systemd.ui_unit_path().write_text(text)
        st = systemd.ui_autostart_state()
        self.assertEqual((st["port"], st["pid"]), (7799, 4242))


if __name__ == "__main__":
    import unittest
    unittest.main()
