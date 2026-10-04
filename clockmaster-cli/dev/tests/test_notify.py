import os
import plistlib
import shlex
from unittest import mock

import base
import identity
import notify
import taskdef
from notify import desktop_linux, desktop_mac, desktop_win, teams, telegram


def msg(status="failed", sound="Blow"):
    t = taskdef.from_text("job", f'schedule: "0 9 * * *"\ncommand: x\nsound: {sound}\n')
    return notify.Message(t, {"status": status, "durationSec": 3.2, "runId": "20260101-090000-1"}, None)


class Gate(base.Case):
    def test_wanted(self):
        self.assertFalse(notify.wanted("off", "failed"))
        self.assertTrue(notify.wanted("on", "success"))
        self.assertTrue(notify.wanted("failure", "killed"))
        self.assertFalse(notify.wanted("failure", "success"))

    def test_dispatch_isolates_channel_crash(self):
        t = taskdef.from_text("job", 'schedule: "0 9 * * *"\ncommand: x\nnotify: on\n')
        boom = mock.Mock(send=mock.Mock(side_effect=RuntimeError("x")))
        ok = mock.Mock()
        with mock.patch.object(notify, "channel", side_effect=lambda n: boom if n == "desktop" else ok):
            notify.dispatch(t, {"status": "success", "runId": "r"})
        self.assertEqual(ok.send.call_count, len(notify.CHANNELS) - 1)  # every other channel still ran
        self.assertIn("desktop channel crashed", notify.log_path().read_text())


class Linux(base.Case):
    def test_argv(self):
        self.assertEqual(desktop_linux.argv(msg()),
                         ["notify-send", "--app-name", identity.TITLE, "--urgency", "critical", "--", "job",
                          msg().body])
        self.assertNotIn("--urgency", desktop_linux.argv(msg("success")))

    def test_headless_is_a_noop_with_note(self):
        self.fake_bin("systemctl", "echo LANG=C\n")
        self.fake_bin("notify-send", f"touch {self.tmp}/sent\n")
        desktop_linux.send(msg())
        self.assertFalse((self.tmp / "sent").exists())
        self.assertIn("no desktop session", notify.log_path().read_text())

    def test_display_from_user_manager(self):
        self.fake_bin("systemctl", "echo WAYLAND_DISPLAY=wayland-0; echo XDG_RUNTIME_DIR=/run/user/1\n")
        self.fake_bin("notify-send", f'echo "$WAYLAND_DISPLAY $*" > {self.tmp}/sent\n')
        desktop_linux.send(msg())
        self.assertTrue((self.tmp / "sent").read_text().startswith("wayland-0 --app-name"))


class Mac(base.Case):
    def test_argv(self):
        a = desktop_mac.argv("/x/notifier", msg(sound="Glass"))
        self.assertEqual(a[0], "/x/notifier")
        self.assertEqual(a[-4:], ["--", "job", msg().body, "Glass"])
        self.assertEqual(desktop_mac.argv("/x", msg(sound="off"))[-1], "")

    def test_conf_and_crumb(self):
        conf = desktop_mac.conf_text()
        self.assertIn(f"CM_ENTRY={shlex.quote(str(identity.ENTRY))}", conf)
        self.assertIn(f"CM_PORT={identity.UI_PORT}", conf)
        self.assertIn("last-notify.json", conf)
        self.assertIn("notify-click.json", conf)
        desktop_mac.write_crumb("job", "r1")
        self.assertIn('"runId": "r1"', desktop_mac.crumb_path().read_text())

    def test_marker_and_plist(self):
        mark = desktop_mac.marker()
        self.assertRegex(mark, r"^\d+\.([0-9a-f]{12}|noicon)$")
        d = plistlib.loads(desktop_mac.info_plist(mark))
        self.assertEqual(d["CFBundleIdentifier"], identity.NOTIFIER_ID)
        self.assertEqual(d["CFBundleVersion"], mark)
        self.assertTrue(d["LSUIElement"])
        self.assertFalse(identity.NOTIFIER_ID.startswith(identity.LAUNCHD_PREFIX))


class Win(base.Case):
    def test_argv_env(self):
        argv, env = desktop_win.argv_env(msg())
        self.assertEqual(argv[0].lower().rstrip(".exe")[-10:], "powershell")
        self.assertEqual((env["CM_TITLE"], env["CM_BODY"]), ("job", msg().body))


class Teams(base.Case):
    def test_off_without_config(self):
        self.assertFalse(teams.settings({}))

    def test_argv(self):
        cfg = {"teams": "on", "teams_team": "T", "teams_channel": "C"}
        s = teams.settings(cfg)
        self.assertTrue(s)
        a = teams.argv(s, msg())
        self.assertIn("channel-post", " ".join(a))
        self.assertIn("job", " ".join(a))


class Telegram(base.Case):
    def test_off_unless_on(self):
        self.assertFalse(telegram.settings({}))
        self.assertFalse(telegram.settings({"teams": "on"}))

    def test_argv_and_text(self):
        s = telegram.settings({"telegram": "on", "telegram_topic": "Jobs", "claude_tg": "/x/claude-tg"})
        self.assertEqual(telegram.argv(s), ["/x/claude-tg", "notify", "--html", "--topic", "Jobs"])
        s = telegram.settings({"telegram": "on", "claude_tg": "/x/claude-tg"})
        self.assertEqual(telegram.argv(s), ["/x/claude-tg", "notify", "--html"])
        t = telegram.text(msg())
        self.assertIn("<b>job</b>", t)
        self.assertIn("exit", t)


if __name__ == "__main__":
    import unittest
    unittest.main()
