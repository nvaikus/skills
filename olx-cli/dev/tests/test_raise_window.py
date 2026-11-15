"""Exit-5 window raise on a shared Xvfb. Run: python3 -m unittest discover -s dev/tests"""
import io
import os
import subprocess
import sys
import time
import unittest
from unittest import mock

import support  # noqa: E402,F401  (sets the test environment first)

from src.api import browser as MOD  # noqa: E402
from src.core import paths  # noqa: E402
from src.core.errors import Waiting as WAITING  # noqa: E402

CFG = {"browser_display": ":99"}


def OWN_PROFILE():
    return str(paths.sub("browser", "profiles", "olx"))


@unittest.skipUnless(sys.platform.startswith("linux"), "X11 raise is Linux-only")
class RaiseWindow(unittest.TestCase):
    """Exit-5 human steps raise the session's own Chrome window on the shared X display (no WM there)."""

    def setUp(self):
        p = mock.patch.dict(os.environ)
        p.start()
        self.addCleanup(p.stop)
        for k in ("DISPLAY", "WAYLAND_DISPLAY"):
            os.environ.pop(k, None)

    def xdo(self, which="/usr/bin/xdotool", wids="111\n"):
        calls = []

        def fake_run(argv, **kw):
            calls.append((argv, kw.get("env", {}).get("DISPLAY")))
            return subprocess.CompletedProcess(argv, 0, wids if argv[1] == "search" else "", "")
        for obj, name, val in ((MOD.shutil, "which", lambda n: which if n == "xdotool" else None),
                               (MOD.subprocess, "run", fake_run)):
            p = mock.patch.object(obj, name, val)
            p.start()
            self.addCleanup(p.stop)
        return calls

    def test_raises_window_of_own_browser_pid(self):
        calls = self.xdo()
        err = io.StringIO()
        with mock.patch.object(MOD, "chrome_pids", return_value=[42]) as pids, mock.patch.object(MOD.sys, "stderr", err):
            e = MOD.human_step(CFG, "sign in")
        self.assertIsInstance(e, WAITING)
        self.assertIn((["/usr/bin/xdotool", "search", "--onlyvisible", "--pid", "42"], ":99"), calls)
        self.assertIn((["/usr/bin/xdotool", "windowraise", "111"], ":99"), calls)
        self.assertTrue(pids.call_args[0][0](OWN_PROFILE()))
        self.assertFalse(pids.call_args[0][0]("/somewhere/else"))
        self.assertEqual(err.getvalue(), "")

    def test_no_xdotool_is_a_note_not_a_failure(self):
        calls = self.xdo(which=None)
        err = io.StringIO()
        with mock.patch.object(MOD.sys, "stderr", err):
            self.assertIsInstance(MOD.human_step(CFG, "sign in"), WAITING)
        self.assertEqual(calls, [])
        self.assertIn("# xdotool not found", err.getvalue())

    def test_chrome_pids_matches_user_data_dir_and_skips_renderers(self):
        prof = f"/tmp/raise-test-{os.getpid()}"
        # Chrome rewrites argv into one space-joined string: the browser process mimics that
        procs = [subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", f"--user-data-dir={prof} {x}"])
                 for x in ("--remote-debugging-port=9", "--type=renderer")]
        try:
            time.sleep(0.2)
            self.assertEqual(MOD.chrome_pids(lambda d: d == prof), [procs[0].pid])
        finally:
            for p in procs:
                p.kill()
                p.wait()


if __name__ == "__main__":
    unittest.main()
