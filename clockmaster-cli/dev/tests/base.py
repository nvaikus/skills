"""Shared test scaffolding: src/ on sys.path and a TestCase whose HOME,
XDG_CONFIG_HOME and CLOCKMASTER_HOME live in a temp dir. Every test uses it,
so nothing here can reach the real data dir or the real user manager."""
import os
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILL / "src"))

import backends  # noqa: E402
import identity  # noqa: E402

ISOLATED = ("HOME", "XDG_CONFIG_HOME", "CLOCKMASTER_HOME", "CLOCKMASTER_SCHEDULER", "PATH",
            "TASK_SCHEDULER_HOME", "DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS",
            "XDG_RUNTIME_DIR", "SHELL", "USER")


class Case(unittest.TestCase):
    scheduler = "null"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cm-test-"))
        self._env = {k: os.environ.get(k) for k in ISOLATED}
        for k in ("DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS", "XDG_RUNTIME_DIR", "TASK_SCHEDULER_HOME"):
            os.environ.pop(k, None)
        os.environ["HOME"] = str(self.tmp / "home")
        os.environ["XDG_CONFIG_HOME"] = str(self.tmp / "home" / ".config")
        os.environ["CLOCKMASTER_HOME"] = str(self.tmp / "data")
        os.environ["CLOCKMASTER_SCHEDULER"] = self.scheduler
        os.environ["USER"] = "tester"
        (self.tmp / "home").mkdir()
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        os.environ["PATH"] = f"{self.bin}{os.pathsep}{self._env['PATH'] or ''}"
        backends._CACHE.clear()

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        backends._CACHE.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_task(self, name, text):
        p = identity.tasks_dir() / f"{name}.yaml"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def fake_bin(self, name, script):
        p = self.bin / name
        p.write_text("#!/bin/sh\n" + script, encoding="utf-8")
        p.chmod(p.stat().st_mode | stat.S_IEXEC)
        return p


class Proc:
    """A subprocess.run result stand-in."""

    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr
