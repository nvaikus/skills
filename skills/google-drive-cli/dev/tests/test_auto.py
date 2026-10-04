"""Automatic onboarding: advance() in mode auto (fake env), the background job's protocol with a
fake browser driver (a Python script speaking the same JSON lines), availability checks."""
import json
import os
import shutil
import sys
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from support import TMP  # noqa: E402  (sets the test environment first)

from src.api import auth, autoconsole, onboarding  # noqa: E402
from src.core import config, paths, profile  # noqa: E402
from test_onboard import FakeEnv  # noqa: E402


def fresh(case, name="au"):
    """A clean profile, removed after the test (other modules expect profile t to be the only one)."""
    shutil.rmtree(Path(TMP) / "root" / name, ignore_errors=True)
    case.addCleanup(shutil.rmtree, Path(TMP) / "root" / name, True)
    profile.resolve(name, "create")
    return config.update()


class AutoMachine(unittest.TestCase):
    def setUp(self):
        fresh(self)
        self.addCleanup(profile.resolve, "t", "required")
        self.notes = []
        p = mock.patch.object(paths, "legacy_config", lambda: Path(TMP) / "no-legacy.json")
        p.start()
        self.addCleanup(p.stop)

    def step(self, env, restart=False, **answers):
        cfg = onboarding.apply(config.load(), answers, self.notes.append)
        return onboarding.advance(env, cfg, "au", self.notes.append, restart=restart)

    def test_signin_then_working_then_done(self):
        env = FakeEnv(who=None, token=False, auto_why=None)
        self.assertEqual(self.step(env)["id"], "mode")
        env.auto_next = {"state": "signin", "step": "signin", "alive": True}
        r = self.step(env, mode="auto", restart=True)
        self.assertEqual((r["status"], r["id"], r["step"], r["now"]), ("waiting", "auto-signin", 3, True))
        self.assertIn("Chrome window", r["say"])
        self.assertEqual(env.did.count("auto_start"), 1)
        env.auto_st = env.auto_next = {"state": "working", "step": "branding", "alive": True, "msg": "home page"}
        r = self.step(env)
        self.assertEqual((r["status"], r["id"], r["step"]), ("running", "auto-branding", 6))
        self.assertEqual(env.did.count("auto_start"), 1)  # a running job is followed, not restarted
        env.auto_st = env.auto_next = {"state": "consent", "step": "login", "alive": True}
        r = self.step(env)
        self.assertEqual((r["status"], r["id"], r["step"]), ("waiting", "auto-consent", 9))
        self.assertIn("Continue", r["say"])
        # the job imported the key and logged in
        config.update(client_id="c", client_secret="s", project_id="personal-drive-1",
                      account={"email": "me@gmail.com", "domain": None, "refresh_expires_in": None})
        env.auto_st = env.auto_next = {"state": "done", "step": "login", "alive": False}
        env.who, env.token = {"email": "me@gmail.com"}, True
        self.assertEqual(self.step(env)["id"], "mount")

    def test_failed_step_falls_back_to_its_manual_text(self):
        config.update(mode="auto", project_id="personal-drive-1", apis_confirmed=True,
                      done_steps=["consent", "branding", "publish"])
        st = {"state": "failed", "step": "client", "alive": False, "msg": "no CREATE button",
              "screenshot": "/x/client.png"}
        env = FakeEnv(who=None, token=False, auto_why=None, auto_st=st)
        r = self.step(env)
        self.assertEqual((r["id"], r["step"]), ("client", 8))
        self.assertIn("could not finish \"creating the key\" (no CREATE button)", r["say"])
        self.assertIn("/x/client.png", r["say"])
        self.assertIn("retry automatic", r["next"])
        self.assertNotIn("auto_start", env.did)
        # the user did that step by hand -> the job resumes with what is left (the login)
        cf = Path(TMP) / "auto-client.json"
        cf.write_text(json.dumps({"installed": {"client_id": "cid", "client_secret": "sec"}}))
        env.auto_next = {"state": "consent", "step": "login", "alive": True}
        r = self.step(env, client_file=str(cf))
        self.assertIn("auto_start", env.did)
        self.assertEqual(r["id"], "auto-consent")

    def test_signin_failure_needs_explicit_retry(self):
        config.update(mode="auto")
        st = {"state": "failed", "step": "signin", "alive": False, "msg": "the browser window was closed"}
        env = FakeEnv(who=None, token=False, auto_why=None, auto_st=st)
        r = self.step(env)
        self.assertEqual(r["id"], "project")
        self.assertIn("browser window was closed", r["say"])
        self.assertNotIn("auto_start", env.did)
        env.auto_next = {"state": "signin", "step": "signin", "alive": True}
        self.assertEqual(self.step(env, mode="auto", restart=True)["id"], "auto-signin")
        self.assertIn("auto_start", env.did)

    def test_unavailable_later_shows_manual(self):
        config.update(mode="auto")
        r = self.step(FakeEnv(who=None, token=False, auto_why="Node.js is not installed"))
        self.assertEqual(r["id"], "project")
        self.assertTrue(any("Node.js is not installed" in n for n in self.notes))


DRIVER = textwrap.dedent('''
    import json, sys, urllib.parse
    plan = json.load(open(sys.argv[1]))
    def emit(o):
        print(json.dumps(o), flush=True)
    emit({"ev": "state", "state": "signin", "step": "signin"})
    emit({"ev": "email", "email": "me@gmail.com"})
    emit({"ev": "project", "id": "personal-drive-424242"})
    emit({"ev": "done", "step": "apis"})
    emit({"ev": "audience", "kind": "external"})
    emit({"ev": "done", "step": "consent"})
    emit({"ev": "done", "step": "branding"})
    emit({"ev": "warn", "step": "publish", "msg": "PUBLISH APP is greyed out"})
    out = plan["outDir"] + "/client.json"
    json.dump({"installed": {"client_id": "cid-1", "client_secret": "sec-1", "project_id": "personal-drive-424242"}},
              open(out, "w"))
    emit({"ev": "client_file", "path": out})
    emit({"ev": "need_consent_url"})
    url = json.loads(sys.stdin.readline())["consent_url"]
    state = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["state"][0]
    emit({"ev": "state", "state": "consent", "step": "login"})
    emit({"ev": "redirect", "url": plan["redirect"] + "?code=abc&state=" + state})
    print(sys.stdin.readline().strip(), file=sys.stderr)  # the quit message
''')


class Job(unittest.TestCase):
    def setUp(self):
        fresh(self, "job")
        self.addCleanup(profile.resolve, "t", "required")
        self.drv = Path(TMP) / "driver.py"
        self.drv.write_text(DRIVER)

    def run_job(self):
        finished = []

        def fake_finish(cfg, cid, secret, code, state):
            finished.append((cid, secret, code))
            config.update(account={"email": "me@gmail.com", "domain": None, "refresh_expires_in": 604799})

        with mock.patch.object(autoconsole, "node", lambda: sys.executable), \
                mock.patch.object(autoconsole, "SCRIPT", self.drv), \
                mock.patch.object(auth, "finish", fake_finish), \
                mock.patch.object(autoconsole.Job, "start_server", lambda self: None), \
                mock.patch("src.api.drive.about", lambda remote: {"user": {}}):
            autoconsole.run_job("job", lambda m: None)
        return finished

    def test_events_drive_the_profile(self):
        (autoconsole.auto_dir("job") / "browser").mkdir(parents=True, exist_ok=True)
        finished = self.run_job()
        cfg = config.load("job")
        self.assertEqual(finished, [("cid-1", "sec-1", "abc")])
        self.assertEqual((cfg["project_id"], cfg["apis_confirmed"], cfg["audience"]), ("personal-drive-424242", True, "external"))
        self.assertEqual(cfg["done_steps"], ["branding", "consent"])  # publish failed: shown by hand later
        self.assertEqual(cfg["client_id"], "cid-1")
        self.assertFalse((autoconsole.auto_dir("job") / "client.json").exists())  # secret file removed
        self.assertFalse((autoconsole.auto_dir("job") / "browser").exists())  # Google session removed
        st = json.loads((autoconsole.auto_dir("job") / "status.json").read_text())
        self.assertEqual(st["state"], "done")
        self.assertTrue(any("greyed out" in w for w in st["warnings"]))
        plan = json.loads((autoconsole.auto_dir("job") / "plan.json").read_text())
        self.assertEqual(plan["todo"], ["project", "apis", "consent", "branding", "publish", "client", "login"])
        self.assertEqual(plan["appName"], "Personal Drive")

    def test_driver_crash_is_a_failure(self):
        self.drv.write_text("import sys\nprint('boom', file=sys.stderr)\n")
        self.run_job()
        st = json.loads((autoconsole.auto_dir("job") / "status.json").read_text())
        self.assertEqual(st["state"], "failed")
        self.assertIn("boom", st["msg"])

    def test_plan_skips_done_work(self):
        config.update("job", project_id="personal-drive-1", apis_confirmed=True, done_steps=["consent"],
                      audience="internal")
        plan = autoconsole.Job("job", print).plan()
        self.assertEqual(plan["todo"], ["client", "login"])

    def test_status_of_a_dead_job(self):
        d = autoconsole.auto_dir("job")
        (d / "status.json").write_text(json.dumps({"state": "working", "pid": 999999, "job": "x"}))
        (d / "job.log").write_text("Traceback\nKeyError: 'x'\n")
        st = autoconsole.status("job")
        self.assertEqual((st["state"], st["alive"]), ("failed", False))
        self.assertIn("KeyError", st["msg"])


class Availability(unittest.TestCase):
    def setUp(self):
        autoconsole._avail.clear()
        self.addCleanup(autoconsole._avail.clear)

    def test_switched_off_and_ssh(self):
        with mock.patch.dict(os.environ, {"GDRIVE_AUTO": "off"}):
            self.assertIn("GDRIVE_AUTO", autoconsole.unavailable())
        autoconsole._avail.clear()
        with mock.patch.dict(os.environ, {"SSH_CONNECTION": "1 2 3 4", "GDRIVE_AUTO": ""}):
            self.assertIn("SSH", autoconsole.unavailable())

    def test_no_node(self):
        env = {k: v for k, v in os.environ.items() if k not in ("SSH_CONNECTION", "GDRIVE_AUTO")}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(autoconsole, "node", lambda: None), \
                mock.patch.object(autoconsole.sys, "platform", "darwin"):
            self.assertEqual(autoconsole.unavailable(), "Node.js is not installed")


if __name__ == "__main__":
    unittest.main()
