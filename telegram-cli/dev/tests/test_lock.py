"""Per-account session lock in tg.connect(): processes on one account serialize; timeout is a clean exit 1.
Run: python3 -m unittest discover -s dev/tests"""
import contextlib
import io
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
TMP = tempfile.mkdtemp(prefix="tg-cli-lock-test-")
os.environ.update(TG_CLI_HOME=TMP, TG_CLI_CONFIG=f"{TMP}/cfg.json", TG_CLI_API_ID="1", TG_CLI_API_HASH="h")
sys.path.insert(0, str(ROOT))

from src import main as main_mod  # noqa: E402
from src.core import config, tg  # noqa: E402
from src.core.errors import CliError  # noqa: E402

# Child process: holds the account lock through a real tg.connect() (fake Telethon), prints LOCKED, then sleeps.
CHILD = textwrap.dedent("""
    import sys, time
    from types import SimpleNamespace
    sys.path.insert(0, sys.argv[1])
    from src.core import tg
    class C:
        def __init__(self, *a, **k): pass
        def connect(self): pass
        def disconnect(self): pass
        def is_user_authorized(self): return True
    tg.telethon = lambda: SimpleNamespace(TelegramClient=C)
    client = tg.connect({"api_id": 1, "api_hash": "h"}, "default")
    print("LOCKED", flush=True)
    time.sleep(float(sys.argv[2]))
    client.disconnect()
    print("RELEASED", time.time(), flush=True)
    time.sleep(float(sys.argv[3]))
""")


class FakeClient:
    def __init__(self, *a, **k):
        self.disconnects = 0

    def connect(self):
        pass

    def disconnect(self):
        self.disconnects += 1

    def is_user_authorized(self):
        return True


FAKE = SimpleNamespace(TelegramClient=FakeClient)
CFG = {"api_id": 1, "api_hash": "h"}


def child(hold, linger=0):
    env = dict(os.environ, TG_CLI_HOME=str(config.HOME))  # config paths are fixed at first import
    p = subprocess.Popen([sys.executable, "-c", CHILD, str(ROOT), str(hold), str(linger)], stdout=subprocess.PIPE,
                         text=True, env=env)
    assert p.stdout.readline().strip() == "LOCKED"
    return p


def stop(p):
    p.kill()
    p.wait()
    p.stdout.close()


@unittest.skipIf(tg.fcntl is None, "flock-based test")
class Lock(unittest.TestCase):
    def setUp(self):
        config.session_path("default").parent.mkdir(parents=True, exist_ok=True)
        config.session_path("default").touch()

    def test_second_process_waits_for_disconnect_then_proceeds(self):
        p = child(hold=1.0, linger=3)  # releases on disconnect, process stays alive afterwards
        try:
            with mock.patch.object(tg, "telethon", lambda: FAKE):
                c = tg.connect(CFG, "default", lock_timeout=10)
            got = time.time()
            released = float(p.stdout.readline().split()[1])
            self.assertGreaterEqual(got, released)
            self.assertIsNone(p.poll())  # lock came from disconnect(), not from process exit
            c.disconnect()
            self.assertEqual(c.disconnects, 1)
            self.assertEqual(tg._held, {})
        finally:
            stop(p)

    def test_timeout_is_exit_1_naming_holder_pid(self):
        p = child(hold=30)
        try:
            err = io.StringIO()
            with mock.patch.object(tg, "telethon", lambda: FAKE), \
                    mock.patch.dict(os.environ, {"TG_CLI_LOCK_TIMEOUT": "0.5", "TG_CLI_API_ID": "1",
                                                 "TG_CLI_API_HASH": "h"}), \
                    contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                t0 = time.monotonic()
                code = main_mod.main(["whoami"])
            self.assertLess(time.monotonic() - t0, 5)
            self.assertEqual(code, 1)
            self.assertIn(f"pid {p.pid}", err.getvalue())
            self.assertIn("TG_CLI_LOCK_TIMEOUT", err.getvalue())
        finally:
            stop(p)

    def test_released_when_holder_process_dies(self):
        stop(child(hold=30))
        with mock.patch.object(tg, "telethon", lambda: FAKE):
            tg.connect(CFG, "default", lock_timeout=2).disconnect()

    def test_reentrant_in_one_process_and_released_on_connect_failure(self):
        with mock.patch.object(tg, "telethon", lambda: FAKE):
            a = tg.connect(CFG, "default", lock_timeout=1)
            b = tg.connect(CFG, "default", lock_timeout=1)  # same process: no self-deadlock
            b.disconnect()
            b.disconnect()  # double disconnect must not drop a's hold
            self.assertEqual(len(tg._held), 1)
            a.disconnect()
        self.assertEqual(tg._held, {})

        class Boom(FakeClient):
            def connect(self):
                raise ConnectionError("down")
        with mock.patch.object(tg, "telethon", lambda: SimpleNamespace(TelegramClient=Boom)):
            with self.assertRaises(ConnectionError):
                tg.connect(CFG, "default", lock_timeout=1)
        self.assertEqual(tg._held, {})

    def test_bad_env_timeout_is_usage_error(self):
        with mock.patch.object(tg, "telethon", lambda: FAKE), \
                mock.patch.dict(os.environ, {"TG_CLI_LOCK_TIMEOUT": "soon"}):
            with self.assertRaises(CliError) as e:
                tg.connect(CFG, "default")
        self.assertEqual(e.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
