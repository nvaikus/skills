"""Onboarding state detection (mocked live checks), answers, legacy import, profile resolution,
login account detection."""
import base64
import json
import os
import shutil
import unittest
from pathlib import Path
from unittest import mock

from support import TMP, run  # noqa: E402  (sets the test environment first)

from src.api import auth, autoconsole, onboarding  # noqa: E402
from src.api import onboard_say as say  # noqa: E402
from src.core import config, paths, profile  # noqa: E402
from src.core.errors import UsageError  # noqa: E402


class FakeEnv:
    """Live checks as plain attributes; actions recorded in .did."""

    def __init__(self, **kw):
        self.rclone = True
        self.who = {"email": "me@gmail.com"}
        self.token = True
        self.disabled = []
        self.drives = ["Team"]
        self.persist_ok = True
        self.mount_status = "mounted"
        self.service = False
        self.index = {"running": False}
        self.auto_why = "no browser here"  # automatic mode unavailable unless a test says so
        self.auto_st = {}                   # what auto_status returns; auto_wait returns auto_next or it
        self.auto_next = None
        self.did = []
        self.__dict__.update(kw)

    def auto_unavailable(self):
        return self.auto_why

    def auto_status(self):
        return self.auto_st

    def auto_start(self, cfg):
        self.did.append("auto_start")
        self.auto_st = {"state": "starting", "alive": True, "job": "j1"}

    def auto_wait(self, st):
        return self.auto_next or st

    def auto_stop(self):
        return False

    def rclone_ok(self):
        return self.rclone

    def install_rclone(self):
        self.did.append("install_rclone")
        self.rclone = True
        return "v9"

    def has_token(self):
        return self.token

    def whoami(self):
        return self.who

    def login_url(self, cfg):
        return "https://accounts.google.com/o/oauth2/v2/auth?fake"

    def disabled_apis(self):
        return self.disabled

    def shared_drives(self):
        return self.drives

    def can_persist(self):
        return self.persist_ok

    def mount_up(self, cfg):
        self.did.append(("mount", cfg["mount"]["what"], bool(cfg["mount"].get("persist"))))
        return self.mount_status

    def service_on(self):
        return self.service

    def install_service(self):
        self.did.append("install_service")

    def index_progress(self):
        return self.index

    def start_index(self):
        self.did.append("start_index")


def fresh(name="ob"):
    shutil.rmtree(Path(TMP) / "root" / name, ignore_errors=True)
    profile.resolve(name, "create")
    return config.update()


class Machine(unittest.TestCase):
    def setUp(self):
        self.cfg = fresh()
        self.addCleanup(profile.resolve, "t", "required")
        self.notes = []
        for p in (mock.patch.object(paths, "legacy_config", lambda: Path(TMP) / "no-legacy.json"),
                  mock.patch.object(paths, "legacy_rclone_conf", lambda: Path(TMP) / "no-legacy.conf")):
            p.start()
            self.addCleanup(p.stop)

    def step(self, env, **answers):
        self.cfg = onboarding.apply(config.load(), answers, self.notes.append)
        return onboarding.advance(env, self.cfg, "ob", self.notes.append)

    def test_walk_through_every_step(self):
        env = FakeEnv(rclone=False, who=None, token=False)
        r = self.step(env)
        self.assertEqual((r["status"], r["step"], r["id"]), ("waiting", 3, "project"))
        self.assertTrue(any("manual steps" in n for n in self.notes))  # no browser automation: manual
        self.assertEqual(config.load()["mode"], "manual")
        self.assertIn("install_rclone", env.did)
        self.assertIn("projectcreate", r["say"])
        self.assertIn("personal-drive", r["say"])
        self.assertIn("--project <PROJECT_ID>", r["next"])
        r = self.step(env, project="personal-drive-123456")
        self.assertEqual(r["id"], "apis")
        self.assertIn("apiid=drive.googleapis.com,docs.googleapis.com,sheets.googleapis.com&project=personal-drive-123456", r["say"])
        r = self.step(env, done=["apis"])
        self.assertEqual((r["id"], r["step"]), ("consent", 5))
        self.assertIn("Personal Drive", r["say"])
        self.assertIn("--audience", r["next"])
        r = self.step(env, done=["consent"], audience="external")
        self.assertEqual((r["id"], r["step"]), ("branding", 6))
        for fact in ("https://nvaikus.github.io/personal-drive/", "privacy.html", "nvaikus.github.io"):
            self.assertIn(fact, r["say"])
        r = self.step(env, done=["branding"])
        self.assertEqual((r["id"], r["step"]), ("publish", 7))
        self.assertIn("Greyed out", r["say"])
        self.assertIn("--keep-testing", r["next"])
        r = self.step(env, done=["publish"])
        self.assertEqual((r["id"], r["step"]), ("client", 8))
        self.assertIn("Desktop app", r["say"])
        cf = Path(TMP) / "client.json"
        cf.write_text(json.dumps({"installed": {"client_id": "cid", "client_secret": "sec", "project_id": "personal-drive-123456"}}))
        r = self.step(env, client_file=str(cf))
        self.assertEqual((r["id"], r["step"]), ("login", 9))
        self.assertIn("https://accounts.google.com", r["say"])
        self.assertIn("login --finish", r["next"])
        for fact in ("Go to Personal Drive (unsafe)", "UNTICKED", "500. That's an error"):
            self.assertIn(fact, r["say"])
        env.who, env.token = {"email": "me@gmail.com"}, True
        env.disabled = ["docs"]
        r = self.step(env)
        self.assertEqual(r["id"], "apis")  # re-verified live after login
        self.assertIn("still switched off: Docs", r["say"])
        self.assertIn("apiid=docs.googleapis.com&", r["say"])
        self.assertFalse(config.load()["apis_confirmed"])
        env.disabled = []
        r = self.step(env)
        self.assertEqual((r["id"], r["step"]), ("mount", 10))
        self.assertIn("Team", r["say"])
        self.assertIn("Shared with me", r["say"])
        self.assertIn("only when you need them", r["say"])  # on-demand indexing: a statement, no question
        self.assertNotIn(("mount", "/", False), env.did)  # nothing mounted before the choices
        r = self.step(env, mount="Clients")
        self.assertEqual((r["id"], r["step"]), ("autostart", 11))
        self.assertEqual(config.load()["mount"]["what"], "/Clients")
        self.assertTrue(config.load()["mount"]["where"].endswith("/gdrive/ob"))
        self.assertNotIn("start_index", env.did)
        r = self.step(env, persist="yes")
        self.assertEqual((r["status"], r["step"]), ("done", 12))
        self.assertIn(("mount", "/Clients", True), env.did)
        self.assertEqual(env.did[-2:], ["install_service", "start_index"])
        self.assertIn("building in the background", r["say"])

    def test_mode_question_when_automation_available(self):
        env = FakeEnv(who=None, token=False, auto_why=None)
        r = self.step(env)
        self.assertEqual((r["status"], r["step"], r["id"]), ("waiting", 2, "mode"))
        self.assertIn("--mode auto", r["next"])
        r = self.step(env, mode="manual")
        self.assertEqual(r["id"], "project")
        self.assertNotIn("auto_start", env.did)

    def test_internal_audience_skips_branding_and_publish(self):
        config.update(mode="manual", project_id="personal-drive-1", apis_confirmed=True)
        r = self.step(FakeEnv(who=None, token=False), done=["consent"], audience="internal")
        self.assertEqual(r["id"], "client")

    def test_unknown_done_step(self):
        with self.assertRaises(UsageError):
            onboarding.apply(config.load(), {"done": ["nope"]}, print)

    def test_rerun_when_done_repeats_nothing(self):
        config.update(client_id="c", client_secret="s", project_id="gdrive-ob-1",
                      mount={"what": "/", "where": "/x", "persist": False})
        env = FakeEnv(service=True, index={"built": True, "running": False, "files": 10, "indexed": 10, "pending": 0})
        r = self.step(env)
        self.assertEqual(r["status"], "done")
        self.assertNotIn("start_index", env.did)
        self.assertNotIn("install_service", env.did)
        self.assertIn("ready (10 files)", r["say"])

    def test_consumer_testing_token_asks_to_publish(self):
        config.update(client_id="c", client_secret="s", project_id="personal-drive-1",
                      account={"email": "me@gmail.com", "domain": None, "refresh_expires_in": 604799})
        r = self.step(FakeEnv())
        self.assertEqual((r["id"], r["step"]), ("branding", 6))
        self.assertIn("ends it every 7 days", r["say"])
        self.assertIn("--keep-testing", r["next"])
        r = self.step(FakeEnv(), done=["branding"])
        self.assertEqual((r["id"], r["step"]), ("publish", 7))
        self.assertIn("auth/audience?project=personal-drive-1", r["say"])
        r = self.step(FakeEnv(), done=["publish"])
        self.assertEqual((r["id"], r["step"]), ("relogin", 9))  # a Testing-era token keeps its 7 days
        self.assertIn("login --finish", r["next"])
        config.update(account={"email": "me@corp.pt", "domain": "corp.pt", "refresh_expires_in": None})
        self.assertEqual(self.step(FakeEnv())["id"], "mount")

    def test_keep_testing_skips_publish(self):
        config.update(client_id="c", client_secret="s", project_id="personal-drive-1",
                      account={"email": "me@gmail.com", "domain": None, "refresh_expires_in": 604799})
        self.assertIn("--keep-testing", self.step(FakeEnv())["next"])
        config.update(keep_testing=True)
        self.assertEqual(self.step(FakeEnv())["id"], "mount")

    def test_refused_token_means_login_again(self):
        config.update(client_id="c", client_secret="s", project_id="gdrive-ob-1")
        r = self.step(FakeEnv(who=None, token=True))
        self.assertIn("no longer works", r["say"])

    def test_no_persist_support_skips_step7(self):
        config.update(client_id="c", client_secret="s", mount={"what": "/", "where": "/x"})
        env = FakeEnv(persist_ok=False, service=None)
        r = self.step(env)
        self.assertEqual(r["status"], "done")
        self.assertIs(config.load()["mount"]["persist"], False)
        self.assertIn("not available here", r["say"])

    def test_mount_still_starting(self):
        config.update(client_id="c", client_secret="s", mount={"what": "/", "where": "/x", "persist": False})
        r = self.step(FakeEnv(mount_status="starting"))
        self.assertEqual(r["status"], "running")

    def test_audience_text_by_account(self):
        cfg = {"project_id": "p-123456", "account": {"email": "me@gmail.com"}}
        self.assertIn("choose \"External\" (", say.consent(cfg))
        cfg["account"] = {"email": "me@corp.pt"}
        self.assertIn("if \"Internal\" can be selected", say.consent(cfg))
        cfg["account"] = {"email": "me@corp.pt", "domain": None}  # logged in: no Workspace domain
        self.assertIn("choose \"External\" (", say.consent(cfg))


class Answers(unittest.TestCase):
    def setUp(self):
        fresh()
        self.addCleanup(profile.resolve, "t", "required")

    def test_project_id_format(self):
        with self.assertRaises(UsageError):
            onboarding.apply(config.load(), {"project": "My Project"}, print)

    def test_client_file_kinds(self):
        p = Path(TMP) / "web.json"
        p.write_text(json.dumps({"web": {"client_id": "x"}}))
        with self.assertRaises(UsageError) as cm:
            onboarding.read_client_file(str(p))
        self.assertIn("Desktop app", str(cm.exception))
        with self.assertRaises(UsageError):
            onboarding.read_client_file(str(Path(TMP) / "missing.json"))

    def test_client_from_another_project_resets_apis(self):
        config.update(project_id="gdrive-a-111111", apis_confirmed=True)
        p = Path(TMP) / "other.json"
        p.write_text(json.dumps({"installed": {"client_id": "c", "client_secret": "s", "project_id": "gdrive-b-222222"}}))
        notes = []
        cfg = onboarding.apply(config.load(), {"client_file": str(p)}, notes.append)
        self.assertEqual((cfg["project_id"], cfg["apis_confirmed"]), ("gdrive-b-222222", False))
        self.assertTrue(any("belongs to project" in n for n in notes))
        self.assertEqual(oct(config.path().stat().st_mode & 0o777), "0o600")

    def test_legacy_import(self):
        legacy = Path(TMP) / "legacy.json"
        legacy.write_text(json.dumps({"client_id": "old-id", "client_secret": "old-sec"}))
        conf = Path(TMP) / "legacy-rclone.conf"
        conf.write_text("[gdrive]\ntype = drive\ntoken = {}\n")
        with mock.patch.object(paths, "legacy_config", lambda: legacy), \
                mock.patch.object(paths, "legacy_rclone_conf", lambda: conf):
            notes = []
            cfg = onboarding.import_legacy(config.load(), notes.append)
        self.assertEqual(cfg["client_id"], "old-id")
        self.assertTrue((profile.dir() / "rclone.conf").exists())
        self.assertEqual(len(notes), 2)

    def test_check_what(self):
        self.assertEqual(onboarding.check_what("/"), "/")
        self.assertEqual(onboarding.check_what("Clients/2026/"), "/Clients/2026")
        self.assertEqual(onboarding.check_what("shared:Team"), "shared:Team")


class Profiles(unittest.TestCase):
    def setUp(self):
        self.root = Path(TMP) / "root2"
        shutil.rmtree(self.root, ignore_errors=True)
        self.addCleanup(profile.resolve, "t", "required")  # runs last (LIFO): after the root is restored
        patch = mock.patch.dict(os.environ, {"GDRIVE_ROOT": str(self.root)})
        patch.start()
        self.addCleanup(patch.stop)

    def make(self, *names):
        for n in names:
            (self.root / n).mkdir(parents=True, exist_ok=True)
            (self.root / n / "config.json").write_text("{}")

    def test_resolution_order(self):
        with self.assertRaises(UsageError) as cm:
            profile.resolve(None, "required")
        self.assertIn("gdrive onboard --profile NAME", str(cm.exception))
        self.assertIsNone(profile.resolve(None, "none"))
        self.make("work")
        self.assertEqual(profile.resolve(None, "required"), "work")  # the only one
        self.make("nj")
        with self.assertRaises(UsageError):
            profile.resolve(None, "required")  # two, no default
        profile.set_default("nj")
        self.assertEqual(profile.resolve(None, "required"), "nj")
        with mock.patch.dict(os.environ, {"GDRIVE_PROFILE": "work"}):
            self.assertEqual(profile.resolve(None, "required"), "work")
        self.assertEqual(profile.resolve("work", "required"), "work")
        self.assertTrue(profile.explicit())
        with self.assertRaises(UsageError):
            profile.resolve("nope", "required")
        self.assertEqual(profile.resolve("newone", "create"), "newone")
        with self.assertRaises(UsageError):
            profile.resolve("Bad Name", "create")

    def test_switch(self):
        self.make("a", "b")
        profile.resolve(None, "none")
        profile.resolve("a", "required")
        with self.assertRaises(UsageError):
            profile.switch("b")  # --profile a was explicit
        profile.set_default("a")
        profile.resolve(None, "required")
        self.assertTrue(profile.switch("b"))
        self.assertEqual(profile.active(), "b")

    def test_global_flag_before_and_after(self):
        self.make("a", "b")
        rc, out, _ = run("--profile", "b", "profiles", "--no-header", "--fields", "profile")
        self.assertEqual((rc, out), (0, "a\nb\n"))
        rc, out, _ = run("profiles", "--default", "b", "--fields", "profile,default", "--no-header")
        self.assertEqual(out, "a\tno\nb\tyes\n")
        rc, _, err = run("whoami", "--profile", "zzz")
        self.assertEqual(rc, 2)
        self.assertIn("no profile 'zzz'", err)

    def test_onboard_cli_exit_codes(self):
        with mock.patch.object(onboarding, "LiveEnv", lambda *a, **k: FakeEnv(who=None, token=False)), \
                mock.patch.object(paths, "legacy_config", lambda: Path(TMP) / "none.json"):
            rc, out, err = run("onboard", "--profile", "fresh")
            self.assertEqual(rc, 5)
            self.assertTrue(out.startswith("WAITING step 3/12 project (profile fresh)\n--- say to the user ---\n"))
            self.assertIn("--- then run ---\ngdrive --profile fresh onboard --project <PROJECT_ID>", out)
            self.assertEqual(profile.root_config()["default_profile"], "fresh")
            rc, out, _ = run("onboard", "--profile", "fresh", "-j")
            self.assertEqual((rc, json.loads(out)["id"]), (5, "project"))


class Login(unittest.TestCase):
    def test_account_of(self):
        claims = base64.urlsafe_b64encode(json.dumps({"email": "a@corp.pt", "hd": "corp.pt"}).encode()).decode().rstrip("=")
        got = auth.account_of({"id_token": f"h.{claims}.s", "refresh_token_expires_in": 604799})
        self.assertEqual(got, {"email": "a@corp.pt", "domain": "corp.pt", "refresh_expires_in": 604799})
        self.assertEqual(auth.account_of({}), {"email": None, "domain": None, "refresh_expires_in": None})

    def test_pending_url_reused(self):
        cfg = {"remote": "gdrive"}
        first = auth.start(cfg, "cid", reuse=True)
        self.assertEqual(auth.start(cfg, "cid", reuse=True), first)
        self.assertNotEqual(auth.start(cfg, "cid"), first)
        self.assertNotEqual(auth.start(cfg, "other", reuse=True), first)


if __name__ == "__main__":
    unittest.main()
