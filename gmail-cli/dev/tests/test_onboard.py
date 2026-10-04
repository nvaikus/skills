"""Onboarding state machine with a fake live environment."""
import json
import os
import shutil
import time
import unittest
from pathlib import Path
from unittest import mock

from support import TMP  # noqa: E402

from src.api import onboarding  # noqa: E402
from src.core import config, profile  # noqa: E402

GD = Path(TMP) / "gdrive"


class FakeEnv:
    def __init__(self, **kw):
        self.token = False
        self.state = "ok"
        self.no_settings = False
        self.did = []
        self.__dict__.update(kw)

    def has_token(self):
        return self.token

    def lacks_settings(self):
        return self.no_settings

    def drop_token(self):
        self.did.append("drop")
        self.token = False

    def login_url(self, cfg):
        return "https://accounts.google.com/o/oauth2/v2/auth?x=1"

    def probe(self):
        return self.state

    def stats(self):
        return {"emailAddress": "me@gmail.com", "messagesTotal": 42}


class TestOnboard(unittest.TestCase):
    def setUp(self):  # own gmail root: the standing profile t must not count as a reusable client
        root = Path(TMP) / "onb"
        shutil.rmtree(GD, ignore_errors=True)
        shutil.rmtree(root, ignore_errors=True)
        env = mock.patch.dict(os.environ, GMAIL_ROOT=str(root))
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(profile.resolve, "t", "create")
        self.notes = []

    def gdrive(self, name, **cfg):
        (GD / name).mkdir(parents=True, exist_ok=True)
        (GD / name / "config.json").write_text(json.dumps({"client_id": f"{name}-cid", "client_secret": "s",
                                                           "project_id": f"{name}-proj", **cfg}))

    def step(self, env, prof="o", relogin=False, **answers):
        profile.resolve(prof, "create")
        cfg = config.update(prof) if prof not in profile.names() else config.load(prof)
        cfg = onboarding.apply(cfg, answers, prof, self.notes.append)
        return onboarding.advance(env, cfg, prof, self.notes.append, relogin=relogin)

    def test_relogin_for_filters_keeps_token(self):
        self.gdrive("o")
        env = FakeEnv(token=True, no_settings=True)
        self.step(env, done=["apis"])
        r = self.step(env)
        self.assertEqual(r["status"], "done")
        self.assertFalse(r["facts"]["filters"])
        self.assertIn("onboard --relogin", r["say"])
        r = self.step(env, relogin=True)
        self.assertEqual(r["id"], "relogin")
        self.assertIn("settings and filters", r["say"])
        self.assertIn("login --finish", r["next"])
        self.assertNotIn("drop", env.did)  # mail keeps working until the new login lands
        env.no_settings = False
        r = self.step(env)
        self.assertTrue(r["facts"]["filters"])
        self.assertNotIn("--relogin", r["say"])

    def test_reuses_gdrive_client_then_apis_login_done(self):
        self.gdrive("other")
        self.gdrive("o")
        env = FakeEnv()
        r = self.step(env)
        self.assertEqual(r["id"], "apis")
        self.assertIn("apiid=gmail.googleapis.com&project=o-proj", r["say"])
        self.assertEqual(config.load("o")["client_from"], "gdrive:o")
        self.assertIn("gdrive:o", self.notes[0])
        r = self.step(env, done=["apis"])
        self.assertEqual(r["id"], "login")
        self.assertIn("login --finish", r["next"])
        env.token = True
        r = self.step(env)
        self.assertEqual(r["status"], "done")
        self.assertEqual(r["facts"]["messages"], 42)
        self.assertTrue(config.load("o")["gmail_api"])
        self.assertEqual(profile.root_config()["default_profile"], "o")

    def test_second_profile_skips_apis(self):
        self.gdrive("x")
        env = FakeEnv(token=True)
        self.step(env, done=["apis"])
        r = self.step(FakeEnv(), prof="p")
        self.assertEqual(r["id"], "login")  # gmail:o proved the API: no apis step
        self.assertEqual(config.load("p")["client_from"], "gmail:o")

    def test_propagating_then_still_off(self):
        self.gdrive("o")
        env = FakeEnv(token=True, state="disabled")
        r = self.step(env, done=["apis"])
        self.assertEqual((r["status"], r["id"], r["now"]), ("running", "apis-propagating", True))
        config.update("o", apis_confirmed_at=time.time() - onboarding.PROPAGATION_S - 1)
        r = self.step(env)
        self.assertEqual(r["id"], "apis")
        self.assertIn("still switched off", r["say"])

    def test_scope_unticked_relogin(self):
        self.gdrive("o")
        env = FakeEnv(token=True, state="scope")
        r = self.step(env, done=["apis"])
        self.assertEqual(r["id"], "login")
        self.assertIn("not ticked", r["say"])
        self.assertEqual(env.did, ["drop"])

    def test_no_client_anywhere_starts_console_steps(self):
        r = self.step(FakeEnv())
        self.assertEqual(r["id"], "project")
        r = self.step(FakeEnv(), project="personal-mail-123")
        self.assertEqual(r["id"], "apis")

    def test_testing_app_branding_publish(self):
        self.gdrive("o")
        env = FakeEnv(token=True)
        profile.resolve("o", "create")
        config.update("o", account={"email": "me@gmail.com", "refresh_expires_in": 604799})
        r = self.step(env, done=["apis"])
        self.assertEqual(r["id"], "branding")
        r = self.step(env, done=["branding"])
        self.assertEqual(r["id"], "publish")
        r = self.step(env, done=["publish"])
        self.assertEqual(r["id"], "relogin")
        self.assertIn("drop", env.did)

    def test_bad_answers(self):
        from src.core.errors import UsageError
        with self.assertRaises(UsageError):
            self.step(FakeEnv(), project="My Project")
        with self.assertRaises(UsageError):
            self.step(FakeEnv(), client_from="nope")


if __name__ == "__main__":
    unittest.main()
