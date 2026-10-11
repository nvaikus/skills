"""Account commands (cart, msg, login) with a mocked playwright-cli. Run: python3 -m unittest discover -s dev/tests"""
import json
import os
import re
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from support import ROOT, fixture, run, write_config  # noqa: E402  (sets the test environment first)
from test_cli import Base  # noqa: E402

from src.api import browser  # noqa: E402
from src.core.errors import UsageError  # noqa: E402

LINE = {"id": "111111111111", "title": "ThinkPad", "price": "EUR 10,00", "shipping": "+ EUR 5,00", "qty": 1,
        "variation": "", "seller": "shop"}


class FakePw:
    """Replaces browser._call: answers `list`, `open`, `run-code` (reads the generated script)."""

    def __init__(self, results=None, is_open=True):
        self.results = results or {}
        self.open = is_open
        self.calls, self.scripts = [], {}

    def __call__(self, args, timeout):
        self.calls.append(args)
        ok = lambda out: subprocess.CompletedProcess(args, 0, out, "")  # noqa: E731
        if args[0] == "list":
            return ok(json.dumps({"browsers": [{"name": "ebay", "status": "open"}] if self.open else []}))
        if args[1] == "open":
            self.open = True
            return ok("opened")
        script = Path(args[-1].split("=", 1)[1])
        action = re.match(r"run-(\w+?)-\d+\.js", script.name).group(1)
        text = script.read_text()
        self.scripts[action] = text
        params = json.loads(re.search(r"const P = (.*);\n", text).group(1))
        res = self.results.get(action, {"status": "ok"})
        res = res(params) if callable(res) else res
        return ok(json.dumps({"result": json.dumps(res)}))

    def params(self, action):
        return json.loads(re.search(r"const P = (.*);\n", self.scripts[action]).group(1))


class AccountBase(Base):
    def pw(self, **kw):
        fake = FakePw(**kw)
        p = mock.patch.object(browser, "_call", fake)
        p.start()
        self.addCleanup(p.stop)
        w = mock.patch.object(browser.shutil, "which", lambda n: "/bin/playwright-cli")
        w.start()
        self.addCleanup(w.stop)
        return fake


class TestBrowser(AccountBase):
    def test_help(self):
        for cmd in ("login", "cart list", "cart add", "cart rm", "msg send", "msg list"):
            rc, out, _ = run(*cmd.split(), "-h")
            self.assertEqual(rc, 0, cmd)
            self.assertIn("usage: ebay", out)

    def test_opens_headed_persistent_when_closed(self):
        fake = self.pw(is_open=False, results={"cart_list": {"status": "ok", "lines": [LINE]}})
        rc, out, _ = run("cart", "list")
        self.assertEqual(rc, 0)
        opened = [c for c in fake.calls if len(c) > 1 and c[1] == "open"][0]
        self.assertEqual(opened[:5], ["-s=ebay", "open", "--browser=chrome", "--headed", "--persistent"])
        p = fake.params("cart_list")
        self.assertEqual(p["domain"], "ebay.de")
        self.assertEqual(self.tsv(out)[0]["id"], "111111111111")

    def test_session_and_market(self):
        fake = self.pw(results={"cart_list": {"status": "ok", "lines": []}})
        with mock.patch.dict("os.environ", {"EBAY_BROWSER_SESSION": "other"}):
            rc, _, err = run("cart", "list", "--market", "EBAY_GB")
        self.assertEqual(rc, 0)
        self.assertIn("cart is empty", err)
        self.assertEqual(fake.calls[-1][0], "-s=other")
        self.assertEqual(fake.params("cart_list")["domain"], "ebay.co.uk")

    def test_not_logged_in_exit_5(self):
        self.pw(results={"cart_list": {"status": "login"}})
        rc, out, err = run("cart", "list")
        self.assertEqual((rc, out), (5, ""))
        self.assertIn("ebay login", err)

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
            with mock.patch.object(browser, "is_open", lambda n: True):
                self.assertEqual(run("cart", "list")[0], 1)
        with mock.patch.object(browser.shutil, "which", lambda n: None):
            with self.assertRaisesRegex(UsageError, "playwright-cli not found"):
                browser._cli()

    def test_login(self):
        self.pw(results={"login": {"status": "ok", "logged_in": False}})
        rc, _, err = run("login")
        self.assertEqual(rc, 5)
        self.assertIn("Chrome window", err)
        self.pw(results={"login": {"status": "ok", "logged_in": True}})
        rc, out, _ = run("login", "-j")
        self.assertEqual((rc, json.loads(out)["logged_in"]), (0, True))

    def test_remote_display_and_view_url(self):
        write_config(market="EBAY_DE", browser_display=":99", browser_view_url="https://box.ts.net/vnc.html")
        self.pw(results={"cart_list": {"status": "login"}, "login": {"status": "ok", "logged_in": False}})
        env = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY")}
        with mock.patch.dict("os.environ", env, clear=True), mock.patch.object(browser.sys, "platform", "linux"):
            rc, _, err = run("cart", "list")
            self.assertEqual(os.environ.get("DISPLAY"), ":99")
        self.assertEqual(rc, 5)
        self.assertIn("https://box.ts.net/vnc.html", err)
        rc, _, err = run("login")
        self.assertEqual(rc, 5)
        self.assertIn("https://box.ts.net/vnc.html", err)
        with mock.patch.dict("os.environ", {"DISPLAY": ":0"}):
            run("cart", "list")
            self.assertEqual(os.environ["DISPLAY"], ":0")


class TestCart(AccountBase):
    def test_add(self):
        fake = self.pw(results={"cart_add": {"status": "ok", "added": True, "lines": [LINE]}})
        rc, out, _ = run("cart", "add", "https://www.ebay.de/itm/111111111111?var=77", "--qty", "2", "-j")
        self.assertEqual(rc, 0)
        self.assertEqual(fake.params("cart_add")["id"], "111111111111")
        self.assertEqual(fake.params("cart_add")["var"], "77")
        self.assertEqual(fake.params("cart_add")["qty"], 2)
        self.assertTrue(json.loads(out)["added"])

    def test_add_variation_by_aspects(self):
        fake = self.pw(results={"cart_add": {"status": "ok", "added": True, "lines": [LINE]}})
        self.assertEqual(run("cart", "add", "444444444444", "--variation", "size=m")[0], 0)
        self.assertEqual(fake.params("cart_add")["var"], "502")
        rc, _, err = run("cart", "add", "444444444444", "--variation", "Size=XXL")
        self.assertEqual(rc, 2)
        self.assertIn("matches 0 of 2", err)
        self.assertEqual(run("cart", "add", "v1|444444444444|501")[0], 0)
        self.assertEqual(fake.params("cart_add")["var"], "501")

    def test_add_already_and_usage(self):
        self.pw(results={"cart_add": {"status": "ok", "added": False, "already": True, "lines": [LINE]}})
        rc, out, err = run("cart", "add", "111111111111")
        self.assertEqual(rc, 0)
        self.assertIn("already in the cart", err)
        self.pw(results={"cart_add": {"status": "usage", "error": "listing has variations: pass --variation"}})
        self.assertEqual(run("cart", "add", "111111111111")[0], 2)
        self.assertEqual(run("cart", "add", "111111111111", "--qty", "0")[0], 2)
        self.assertEqual(run("cart", "add", "not-an-id")[0], 2)

    def test_rm(self):
        fake = self.pw(results={"cart_rm": {"status": "ok", "results": [{"id": "111111111111", "removed": 1}], "lines": []}})
        rc, out, err = run("cart", "rm", "https://www.ebay.de/itm/111111111111")
        self.assertEqual(rc, 0)
        self.assertEqual(fake.params("cart_rm")["ids"], ["111111111111"])
        self.assertEqual(self.tsv(out)[0]["removed"], "1")
        self.assertIn("0 line(s)", err)


class TestMsg(AccountBase):
    def test_send_seller_from_api_and_stdin(self):
        sent = lambda p: {"status": "ok", "seller": p["seller"], "count": 2,  # noqa: E731
                          "message": {"who": "Sie", "day": "Heute", "time": "18:41", "text": p["text"]}}
        fake = self.pw(results={"msg_send": sent})
        rc, out, _ = run("msg", "send", "111111111111", "-j", stdin="Is it tested?\n")
        self.assertEqual(rc, 0)
        self.assertEqual(fake.params("msg_send")["seller"], "laptopshop")
        r = json.loads(out)
        self.assertEqual((r["from"], r["time"], r["text"]), ("me", "18:41", "Is it tested?"))
        run("msg", "send", "111111111111", "hi", "--seller", "bob")
        self.assertEqual(fake.params("msg_send")["seller"], "bob")

    def test_send_usage(self):
        self.pw()
        self.assertEqual(run("msg", "send", "111111111111")[0], 2)  # tty, no text
        self.assertEqual(run("msg", "send", "111111111111", "  ")[0], 2)
        self.assertEqual(run("msg", "send", "111111111111", "x" * 2001)[0], 2)

    def test_list_inbox_and_thread(self):
        row = {"conversation": "1", "kind": "member", "from": "shop", "subject": "S", "last": "yes",
               "last_by": "them", "unread": True, "when": "2 Min"}
        msgs = [{"who": "Sie", "day": "Heute", "time": "18:41", "text": "q\nline2"},
                {"who": "laptopshop", "day": "Heute", "time": "19:00", "text": "a"}]
        fake = self.pw(results={"msg_list": lambda p: {"status": "ok", "rows": [row]} if not p["id"]
                                else {"status": "ok", "seller": p["seller"], "messages": msgs}})
        rc, out, _ = run("msg", "list")
        self.assertEqual((rc, self.tsv(out)[0]["last_by"]), (0, "them"))
        rc, out, _ = run("msg", "list", "--item", "111111111111")
        rows = self.tsv(out)
        self.assertEqual([r["from"] for r in rows], ["me", "laptopshop"])
        self.assertEqual(rows[0]["text"], "q ↵ line2")
        self.assertEqual(fake.params("msg_list")["seller"], "laptopshop")

    def test_thread_translated_seller_reply(self):
        self.pw(results={"msg_list": fixture("msg_thread_translated.json")})
        rc, out, _ = run("msg", "list", "--item", "377528863273", "--seller", "ttz0422")
        rows = self.tsv(out)
        self.assertEqual(rc, 0)
        self.assertEqual([(r["from"], r["day"], r["time"]) for r in rows], [("me", "Heute", "18:41"), ("ttz0422", "Heute", "18:59")])
        self.assertTrue(rows[1]["text"].startswith("Sehr geehrter Kunde, ↵ Unser"))
        rc, out, _ = run("msg", "list", "--item", "377528863273", "--seller", "ttz0422", "-j")
        m = json.loads(out)[1]
        self.assertEqual((m["translated"], m["original"].splitlines()[0]), (True, "Dear Customer,"))
        self.assertIsNone(json.loads(out)[0]["original"])

    def test_thread_js_reads_time_span_and_avatar(self):
        # live 2026-10-10: posted-time also holds the "Übersetzt" label; the other side's aria-label has no colon
        js = (ROOT / "src" / "api" / "js" / "prelude.js").read_text()
        self.assertIn("message-bubble_posted-time] > .ux-textspans", js)
        self.assertIn("message-bubble__avatar] [role=img]", js)
        self.assertIn("app-conversation]')].reverse()", js)


class TestRailsBrowser(unittest.TestCase):
    def test_js_never_touches_checkout_pay_bid_offer(self):
        pat = re.compile(r"checkout|kasse|x-bin|buy-it-now|bin-action|pay|bid|offer|sofort", re.I)
        for p in (ROOT / "src" / "api" / "js").glob("*.js"):
            for n, line in enumerate(p.read_text().splitlines(), 1):
                self.assertIsNone(pat.search(line), f"{p.name}:{n}: {line.strip()}")


if __name__ == "__main__":
    unittest.main()
