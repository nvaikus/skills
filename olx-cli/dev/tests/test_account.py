"""Account commands (login, msg) with a mocked playwright-cli. Run: python3 -m unittest discover -s dev/tests"""
import io
import json
import re
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from support import ROOT, fixture, run, write_config  # noqa: E402  (sets the test environment first)
from test_cli import Base  # noqa: E402

from src.api import account, browser  # noqa: E402
from src.core.errors import UsageError  # noqa: E402

VIEW = "https://view.example/vnc.html"


class FakePw:
    """Replaces browser._call: answers `list`, `attach`, `run-code` (reads the generated script)."""

    def __init__(self, results=None, attached=True):
        self.results = results or {}
        self.attached = attached
        self.name = "olx"
        self.calls, self.scripts = [], {}

    def __call__(self, args, timeout):
        self.calls.append(args)
        ok = lambda out: subprocess.CompletedProcess(args, 0, out, "")  # noqa: E731
        if args[0] == "list":
            return ok(json.dumps({"browsers": [{"name": self.name, "status": "open"}] if self.attached else []}))
        if args[1] == "attach":
            self.attached, self.name = True, args[0].removeprefix("-s=")
            return ok("attached")
        script = Path(args[-1].split("=", 1)[1])
        action = re.match(r"run-(\w+?)-\d+\.js", script.name).group(1)
        text = script.read_text()
        self.scripts[action] = text
        res = self.results.get(action, {"status": "ok"})
        res = res(self.params(action)) if callable(res) else res
        return ok(json.dumps({"result": json.dumps(res)}))

    def params(self, action):
        return json.loads(re.search(r"const P = (.*);\n", self.scripts[action]).group(1))


class AccountBase(Base):
    def pw(self, up=True, **kw):
        fake = FakePw(**kw)
        for obj, name, val in ((browser, "_call", fake), (browser.shutil, "which", lambda n: "/bin/playwright-cli"),
                               (browser, "debug_up", lambda cfg: up)):
            p = mock.patch.object(obj, name, val)
            p.start()
            self.addCleanup(p.stop)
        return fake


class TestBrowser(AccountBase):
    def test_help(self):
        for cmd in ("login", "msg send", "msg list"):
            rc, out, _ = run(*cmd.split(), "-h")
            self.assertEqual(rc, 0, cmd)
            self.assertIn("usage: olx", out)
        rc, out, _ = run("msg")
        self.assertIn("msg send", out)

    def test_attaches_over_cdp_to_running_chrome(self):
        fake = self.pw(attached=False, results={"msg_list": {"status": "ok", "rows": []}})
        rc, _, err = run("msg", "list")
        self.assertEqual(rc, 0)
        self.assertIn("inbox is empty", err)
        self.assertIn(["-s=olx", "attach", "--cdp=http://127.0.0.1:9335"], fake.calls)
        p = fake.params("msg_list")
        self.assertEqual((p["host"], p["limit"]), ("www.olx.pt", 25))

    def test_starts_plain_chrome_when_port_is_down(self):
        self.pw(up=False, results={"login": {"status": "ok", "logged_in": True}})
        with mock.patch.object(browser, "start_chrome") as start:
            rc, out, _ = run("login", "--site", "pl")
        self.assertEqual(rc, 0)
        start.assert_called_once()
        self.assertEqual(out.strip().split("\t"), ["yes", "olx", "www.olx.pl"])

    def test_launch_argv_plain_chrome_with_prefix(self):
        cfg = {"browser_launch_prefix": ["systemd-run", "--user", "--unit=olx-browser-{ts}", "--setenv=DISPLAY={display}"],
               "browser_display": ":99", "browser_chrome": "/usr/bin/chrome", "browser_port": 9400}
        argv = browser.launch_argv(cfg, "olx", "about:blank")
        self.assertEqual(argv[:2], ["systemd-run", "--user"])
        self.assertRegex(argv[2], r"^--unit=olx-browser-\d+$")
        self.assertEqual(argv[3], "--setenv=DISPLAY=:99")
        self.assertIn("/usr/bin/chrome", argv)
        self.assertIn("--remote-debugging-port=9400", argv)
        self.assertTrue(any(a.startswith("--user-data-dir=") and a.endswith("profiles/olx") for a in argv))
        self.assertFalse(any("headless" in a or "enable-automation" in a for a in argv))

    def test_session_and_port_from_env(self):
        fake = self.pw(attached=False, results={"msg_list": {"status": "ok", "rows": []}})
        with mock.patch.dict("os.environ", {"OLX_BROWSER_SESSION": "other", "OLX_BROWSER_PORT": "9401"}):
            self.assertEqual(run("msg", "list")[0], 0)
        self.assertIn(["-s=other", "attach", "--cdp=http://127.0.0.1:9401"], fake.calls)

    def test_not_logged_in_exit_5_carries_view_link(self):
        write_config(site="pt", browser_view_url=VIEW)
        self.pw(results={"msg_list": {"status": "login"}})
        rc, out, err = run("msg", "list")
        self.assertEqual((rc, out), (5, ""))
        self.assertIn("olx login", err)
        self.assertIn(VIEW, err)

    def test_login_signed_out_exit_5(self):
        write_config(site="pt", browser_view_url=VIEW)
        self.pw(results={"login": {"status": "ok", "logged_in": False}})
        rc, _, err = run("login")
        self.assertEqual(rc, 5)
        self.assertIn(VIEW, err)
        self.assertIn("rerun `olx login`", err)

    def test_captcha_exit_5(self):
        self.pw(results={"msg_list": {"status": "captcha"}})
        rc, _, err = run("msg", "list")
        self.assertEqual(rc, 5)
        self.assertIn("captcha", err)

    def test_failure_dumps(self):
        self.pw(results={"msg_list": {"status": "fail", "step": "open-inbox", "error": "Timeout", "url": "https://x",
                                      "title": "T", "aria": "- main", "png": None}})
        rc, _, err = run("msg", "list")
        self.assertEqual(rc, 1)
        m = re.search(r"dump: (\S+\.txt)", err)
        self.assertIsNotNone(m, err)
        self.assertIn("- main", Path(m.group(1)).read_text())

    def test_script_error_and_missing_cli(self):
        self.pw()
        with mock.patch.object(browser, "_call", lambda a, t: subprocess.CompletedProcess(a, 0, '{"isError": true, "error": "x"}', "")):
            with mock.patch.object(browser, "attached", lambda n: True):
                self.assertEqual(run("msg", "list")[0], 1)
        with mock.patch.object(browser.shutil, "which", lambda n: None):
            with self.assertRaisesRegex(UsageError, "playwright-cli not found"):
                browser._cli()

    def test_usage_from_page(self):
        self.pw(results={"msg_list": {"status": "usage", "error": "listing 674669746 shows no \"send message\" button"}})
        rc, _, err = run("msg", "list", "--id", "674669746")
        self.assertEqual(rc, 2)
        self.assertIn("send message", err)


class TestMsg(AccountBase):
    def test_send_passes_listing_url_and_text(self):
        fake = self.pw(results={"msg_send": {"status": "ok", "count": 3, "conversation": "c9",
                                             "message": {"mine": True, "time": "14:05", "text": "Ainda disponível?"}}})
        rc, out, _ = run("msg", "send", "674669746", "Ainda disponível?")
        self.assertEqual(rc, 0)
        p = fake.params("msg_send")
        self.assertEqual(p["id"], 674669746 if isinstance(p["id"], int) else "674669746")
        self.assertTrue(p["url"].startswith("https://www.olx.pt/d/anuncio/"))
        self.assertEqual(p["text"], "Ainda disponível?")
        self.assertEqual(out.strip().split("\t")[1:], ["Helder", "c9", "14:05", "Ainda disponível?"])

    def test_send_reads_stdin_and_checks_text(self):
        fake = self.pw(results={"msg_send": {"status": "ok", "message": {"mine": True, "time": "1", "text": "x"}}})
        with mock.patch("sys.stdin", io.StringIO("  from stdin \n")):
            self.assertEqual(run("msg", "send", "674669746")[0], 0)
        self.assertEqual(fake.params("msg_send")["text"], "from stdin")
        with mock.patch("sys.stdin", io.StringIO("   ")):
            self.assertEqual(run("msg", "send", "674669746")[0], 2)
        self.assertEqual(run("msg", "send", "674669746", "x" * 5001)[0], 2)

    def test_send_chat_disabled_never_opens_browser(self):
        fake = self.pw()
        offer = fixture("offer.json")
        offer["data"]["contact"]["chat"] = False
        self.fake_offer(offer)
        rc, _, err = run("msg", "send", "674669746", "hi")
        self.assertEqual(rc, 2)
        self.assertIn("does not take OLX chat", err)
        self.assertEqual(fake.calls, [])

    def fake_offer(self, body):
        orig = self.fake.__class__.__call__

        def call(url, params=None, want="json"):
            if "/api/v1/offers/674669746/" in url:
                return body
            return orig(self.fake, url, params, want)
        p = mock.patch("src.core.http.get", call)
        p.start()
        self.addCleanup(p.stop)

    def test_send_unknown_listing_exit_2(self):
        fake = self.pw()
        self.assertEqual(run("msg", "send", "111", "hi")[0], 2)
        self.assertEqual(fake.calls, [])

    def test_thread_by_listing(self):
        msgs = [{"mine": True, "who": "Mensagem tua", "time": "10:00", "text": "Olá"},
                {"mine": False, "who": "Mensagem de Helder", "time": "10:05", "text": "Sim, disponível"}]
        fake = self.pw(results={"msg_list": {"status": "ok", "conversation": "c9", "messages": msgs}})
        rc, out, err = run("msg", "list", "--id", "674669746")
        self.assertEqual(rc, 0)
        self.assertEqual([r["from"] for r in self.tsv(out)], ["me", "Helder"])
        self.assertIn("conversation c9", err)
        self.assertIsNone(fake.params("msg_list")["conversation"])

    def test_thread_by_conversation_skips_listing_lookup(self):
        fake = self.pw(results={"msg_list": {"status": "ok", "conversation": "c9", "messages": []}})
        rc, _, err = run("msg", "list", "--conversation", "c9")
        self.assertEqual(rc, 0)
        self.assertIn("no messages", err)
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(fake.params("msg_list")["conversation"], "c9")

    def test_inbox_rows(self):
        rows = [{"conversation": "c9", "from": "Helder", "ad": "Bicicleta", "last": "Sim", "last_by": "them",
                 "unread": True, "when": "10:05"}]
        self.pw(results={"msg_list": {"status": "ok", "rows": rows}})
        rc, out, _ = run("msg", "list", "--limit", "5")
        self.assertEqual(rc, 0)
        self.assertEqual(self.tsv(out)[0]["last_by"], "them")
        self.assertEqual(run("msg", "list", "--limit", "0")[0], 2)


class TestScripts(unittest.TestCase):
    def test_generated_script_wraps_prelude_and_params(self):
        s = browser.script("msg_send", {"text": "a\"b", "T": browser.TIMEOUTS})
        self.assertTrue(s.startswith("async page => {"))
        self.assertIn('const P = {"text": "a\\"b"', s)
        self.assertIn("return {status: 'login'", s)

    def test_rail_no_posting_buying_paying(self):
        for f in (ROOT / "src" / "api" / "js").glob("*.js"):
            code = "\n".join(ln for ln in f.read_text().splitlines() if not ln.strip().startswith("//"))
            self.assertIsNone(re.search(r"/adding|/payment|checkout|Comprar|Anunciar|Pagar|buy-from-chat|go-to-checkout",
                                        code, re.I), f.name)

    def test_every_wait_is_bounded(self):
        for f in (ROOT / "src" / "api" / "js").glob("*.js"):
            for ln in f.read_text().splitlines():
                if re.search(r"\.(waitFor|goto|click|fill|waitForLoadState)\(", ln):
                    self.assertRegex(ln, r"timeout", f"{f.name}: {ln.strip()}")

    def test_who(self):
        self.assertEqual(account._who({"mine": True}, "Helder"), "me")
        self.assertEqual(account._who({"mine": False, "who": "x"}, None), "x")


if __name__ == "__main__":
    unittest.main()
