"""Declutter: quota pacing/retry, partial results, senders, unsubscribe, filters."""
import json
import re
import unittest
from pathlib import Path
from unittest import mock

from support import TMP, run  # noqa: E402  (sets the test environment first)
from test_cli import Base, FakeGmail, msg, raw_of  # noqa: E402

from src.api import auth, google, unsubscribe  # noqa: E402
from src.core import http  # noqa: E402
from src.core.errors import CliError  # noqa: E402

ONE_CLICK = [("List-Unsubscribe", "<mailto:leave@shop.com?subject=stop>, <https://shop.com/u/1>"),
             ("List-Unsubscribe-Post", "List-Unsubscribe=One-Click")]


class CleanGmail(FakeGmail):
    """+ filters routes and outside (non-Google) URLs for the one-click POST."""

    def __init__(self):
        super().__init__()
        self.posts, self.filters, self.fail, self.queries = [], {}, {}, []
        b = self.box["t"]["messages"]
        for m in (msg("n1", "nt1", "Shop News <news@shop.com>", "Sale 1", 1_700_000_500_000, "a", q="promo",
                      labels=("INBOX", "UNREAD", "CATEGORY_PROMOTIONS"), extra_headers=ONE_CLICK),
                  msg("n2", "nt1", "Shop News <news@shop.com>", "Sale 2", 1_700_000_600_000, "b", q="promo",
                      labels=("INBOX", "CATEGORY_PROMOTIONS"), extra_headers=ONE_CLICK),
                  msg("n3", "nt3", "news@shop.com", "Sale 3", 1_700_000_700_000, "c", q="promo",
                      labels=("UNREAD", "CATEGORY_PROMOTIONS"), extra_headers=ONE_CLICK),
                  msg("d1", "dt1", "Digest <digest@list.org>", "Weekly", 1_700_000_200_000, "d", q="promo",
                      labels=("CATEGORY_UPDATES",), extra_headers=[("List-Unsubscribe", "<https://list.org/out>")]),
                  msg("p1", "pt1", "Pal <pal@x.org>", "hello", 1_700_000_250_000, "e", q="promo",
                      extra_headers=[("List-Unsubscribe", "<mailto:off@x.org>")])):
            b[m["id"]] = m

    def __call__(self, method, url, params=None, body=None, headers=None, allow_mutate=False, **kw):
        if "googleapis.com" not in url:
            if method != "GET" and not allow_mutate:
                raise RuntimeError("transport rail")
            self.posts.append((method, url, kw.get("data")))
            if url in self.fail:
                raise CliError(f"HTTP {self.fail[url]}", status=self.fail[url])
            return None
        path = url.split("users/me", 1)[1]
        if params and params.get("q"):
            self.queries.append(params["q"])  # the base fake matches bare words: from:(x) -> x
            params = {**params, "q": re.sub(r"-?\w+:\(?([^)\s]+)\)?", r"\1", params["q"])}
        mid = path.split("/")[-1]
        if path.startswith("/messages/") and mid in self.fail:
            self.calls.append(("t", method, path, params, body))
            raise CliError("boom", status=self.fail[mid], body={"error": {"message": "boom"}})
        if path.startswith("/settings/filters"):
            prof = headers["Authorization"].split("tok-")[1]
            self.calls.append((prof, method, path, params, body))
            fid = path[len("/settings/filters/"):]
            if method == "GET" and not fid:
                return {"filter": list(self.filters.values())} if self.filters else {}
            if method == "POST":
                f = {"id": f"F{len(self.filters) + 1}", **body}
                self.filters[f["id"]] = f
                return f
            if fid not in self.filters:
                raise self.err(404)
            return self.filters.pop(fid) if method == "DELETE" else self.filters[fid]
        return super().__call__(method, url, params, body, headers, allow_mutate, **kw)


class CleanBase(Base):
    def setUp(self):
        super().setUp()
        self.g = CleanGmail()
        p = mock.patch.object(http, "request", self.g)
        p.start()
        self.addCleanup(p.stop)
        tok = Path(f"{TMP}/root/t/token.json")
        self.addCleanup(lambda: tok.unlink(missing_ok=True))

    def scopes(self, *extra):
        Path(f"{TMP}/root/t/token.json").write_text(json.dumps(
            {"access_token": "x", "refresh_token": "r", "expires": 9e12,
             "scope": " ".join((auth.GMAIL_SCOPE,) + extra)}))


class FakeClock:
    def __init__(self):
        self.now, self.slept = 0.0, []

    def __call__(self):
        return self.now

    def sleep(self, s):
        self.slept.append(s)
        self.now += s


class TestQuota(unittest.TestCase):
    def test_pacer_burst_then_rate(self):
        c = FakeClock()
        p = google.Pacer(rate=100, burst=50, clock=c, sleep=c.sleep)
        for _ in range(10):
            p.take(5)  # the burst: no wait
        self.assertEqual(c.slept, [])
        p.take(5)
        self.assertAlmostEqual(sum(c.slept), 0.05)

    def test_pacer_hit_recalibrates(self):
        c = FakeClock()
        p = google.Pacer(rate=1000, burst=5000, clock=c, sleep=c.sleep)
        for _ in range(400):  # 2000 units, then Gmail says 'too fast'
            p.take(5)
        c.now = 20.0
        self.assertEqual(p.hit(2), (2, True))
        self.assertAlmostEqual(p.per_min(), 2000)  # the cap the window really held
        self.assertEqual(p.hit(2), (2.0, False))  # a second thread inside the pause: same wait, no note
        p.take(5)
        self.assertGreaterEqual(c.now, 22.0)
        c.now = 30.0  # the burst still fills Gmail's window: wait, keep the rate, no note yet
        self.assertEqual(p.hit(3), (3, False))
        self.assertAlmostEqual(p.per_min(), 2000)
        c.now = 200.0  # refused at the calibrated pace: 5% slower, note again
        self.assertTrue(p.hit(1)[1])
        self.assertAlmostEqual(p.per_min(), 1900)

    def test_costs(self):
        self.assertEqual(google.cost("GET", "/messages/x"), 5)
        self.assertEqual(google.cost("GET", "/threads/x"), 10)
        self.assertEqual(google.cost("GET", "/labels"), 1)
        self.assertEqual(google.cost("POST", "/messages/send"), 100)

    def quota_err(self, status=403, after=None):
        e = CliError("HTTP 403", status=status, body={"error": {
            "message": "Quota exceeded for quota metric 'Total Query Cost'", "status": "PERMISSION_DENIED",
            "errors": [{"reason": "rateLimitExceeded", "domain": "usageLimits"}],
            "details": [{"reason": "RATE_LIMIT_EXCEEDED", "metadata": {"quota_limit_value": "6000"}}]}})
        e.retry_after = after
        return e

    def call_with(self, outcomes):
        c, notes = FakeClock(), []
        seq = list(outcomes)

        def fake(*a, **kw):
            self.assertFalse(kw["rate_retry"])  # google owns 429 handling
            o = seq.pop(0)
            if isinstance(o, Exception):
                raise o
            return o
        with mock.patch.object(google.http, "request", fake), \
                mock.patch.object(google.auth, "access_token", lambda p: "tok"), \
                mock.patch.object(google, "notice", notes.append), \
                mock.patch.dict(google._pacers, {"q": google.Pacer(clock=c, sleep=c.sleep)}):
            try:
                return google.get("q", "/messages/1"), notes, c
            except CliError as e:
                return e, notes, c

    def test_retry_on_403_quota_and_429(self):
        got, notes, c = self.call_with([self.quota_err(after=7), self.quota_err(429), {"id": "1"}])
        self.assertEqual(got, {"id": "1"})
        self.assertGreaterEqual(c.now, 7)  # Retry-After honored
        self.assertEqual(len(notes), 1)  # one note per profile a minute, not one per retry
        self.assertIn("quota reached (6000 units/min)", notes[0])

    def test_gives_up_after_cap(self):
        got, notes, c = self.call_with([self.quota_err(after=60)] * 10)
        self.assertIsInstance(got, CliError)
        self.assertIn("still rate-limited", str(got))
        self.assertLess(c.now, google.MAX_WAIT + 70)

    def test_daily_limit_not_retried(self):
        e = CliError("x", status=403, body={"error": {"message": "daily", "errors": [{"reason": "dailyLimitExceeded"}]}})
        got, notes, _ = self.call_with([e])
        self.assertIsInstance(got, CliError)
        self.assertEqual(notes, [])

    def test_http_retry_after_header(self):
        self.assertEqual(http.retry_after({"Retry-After": "12"}), 12.0)
        self.assertIsNone(http.retry_after({"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"}))


class TestPartial(CleanBase):
    def test_search_keeps_rows_on_failure(self):
        self.g.fail["m1"] = 500
        rc, out, err = run("search", "--limit", "50", "")
        self.assertEqual(rc, 1)
        self.assertIn("incomplete", err)
        self.assertIn("rows above are incomplete", err)
        self.assertGreaterEqual(len(self.tsv(out)), 1)


class TestSenders(CleanBase):
    def test_aggregate_sort_and_columns(self):
        rc, out, err = run("senders", "promo", "-j")
        self.assertEqual(rc, 0, err)
        rows = json.loads(out)
        self.assertEqual(rows[0]["sender"], "news@shop.com")
        self.assertEqual((rows[0]["count"], rows[0]["unread"]), (3, 2))
        self.assertEqual(rows[0]["name"], "Shop News")
        self.assertEqual(rows[0]["category"], "promotions")
        self.assertEqual(rows[0]["subject"], "Sale 3")  # newest
        self.assertEqual(rows[0]["unsubscribe"], "one-click")
        by = {r["sender"]: r for r in rows}
        self.assertEqual(by["digest@list.org"]["unsubscribe"], "url")
        self.assertEqual(by["pal@x.org"]["unsubscribe"], "mailto")
        self.assertEqual(by["pal@x.org"]["category"], "-")
        # the two-message thread came in one threads.get
        self.assertTrue(any(c[2] == "/threads/nt1" for c in self.g.calls))
        self.assertFalse(any(c[2] in ("/messages/n1", "/messages/n2") for c in self.g.calls))

    def test_min_limit_and_default_query(self):
        rc, out, err = run("senders", "promo", "--min", "2")
        self.assertEqual([r["sender"] for r in self.tsv(out)], ["news@shop.com"])
        rc, out, err = run("senders", "promo", "--limit", "2")
        self.assertIn("newest 2 matches only", err)
        run("senders")
        self.assertEqual(self.g.queries[-1], "newer_than:1y -from:me")

    def test_every_profile(self):
        self.two()
        rc, out, err = run("senders", "invoice")
        self.assertEqual(rc, 0, err)
        self.assertEqual({r["profile"] for r in self.tsv(out)}, {"t", "w"})


class TestUnsubscribe(CleanBase):
    def test_parse(self):
        lk = unsubscribe.links({"list-unsubscribe": "<mailto:a@b.c>, <https://x/u>",
                                "list-unsubscribe-post": "List-Unsubscribe=One-Click"})
        self.assertEqual(lk, {"one_click": "https://x/u", "mailto": "mailto:a@b.c", "url": "https://x/u"})
        self.assertEqual(unsubscribe.kind({"list-unsubscribe": "<http://x/u>",
                                           "list-unsubscribe-post": "List-Unsubscribe=One-Click"}), "url")
        self.assertEqual(unsubscribe.kind({}), "-")

    def test_dry_run_acts_on_nothing(self):
        rc, out, err = run("unsubscribe", "news@shop.com", "digest@list.org", "pal@x.org", "m1", "--dry-run")
        self.assertEqual(rc, 0, err)
        rows = {r["target"]: r for r in self.tsv(out)}
        self.assertEqual(rows["news@shop.com"]["method"], "one-click")
        self.assertEqual(rows["news@shop.com"]["result"], "would POST https://shop.com/u/1")
        self.assertEqual((rows["digest@list.org"]["method"], rows["digest@list.org"]["result"]),
                         ("manual", "https://list.org/out"))
        self.assertEqual(rows["pal@x.org"]["result"], "would mail mailto:off@x.org")
        self.assertEqual(rows["m1"]["method"], "-")
        self.assertEqual(self.g.posts, [])
        self.assertFalse([c for c in self.g.calls if c[1] != "GET"])

    def test_safe_url_quotes_spaces(self):
        from src.api.unsubscribe import safe_url
        self.assertEqual(safe_url("https://x.com/u?t=be: In&a=%3D"), "https://x.com/u?t=be:%20In&a=%3D")

    def test_one_click_then_mailto_fallback(self):
        rc, out, err = run("unsubscribe", "news@shop.com")
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.g.posts, [("POST", "https://shop.com/u/1", b"List-Unsubscribe=One-Click")])
        self.assertEqual(self.tsv(out)[0]["result"], "done")
        self.g.fail["https://shop.com/u/1"] = 500
        rc, out, err = run("unsubscribe", "news@shop.com")
        self.assertEqual(rc, 0, err)
        r = self.tsv(out)[0]
        self.assertEqual(r["method"], "mailto")
        self.assertIn("one-click failed", r["result"])
        e = raw_of(self.g.box["t"]["sent"][-1])
        self.assertEqual((e["To"], e["Subject"]), ("leave@shop.com", "stop"))

    def test_mailto_and_unknown(self):
        rc, out, err = run("unsubscribe", "pal@x.org", "nobody@none.org")
        self.assertEqual(rc, 1)
        rows = {r["target"]: r for r in self.tsv(out)}
        self.assertTrue(rows["pal@x.org"]["result"].startswith("sent "))
        self.assertIn("no mail from", rows["nobody@none.org"]["result"])
        self.assertIn("unsubscribe failed for: nobody@none.org", err)


class TestFilters(CleanBase):
    def test_needs_settings_scope(self):
        self.scopes()
        rc, out, err = run("filter", "create", "--from", "news@shop.com", "--archive")
        self.assertEqual(rc, 2)
        self.assertIn("gmail --profile NAME onboard --relogin", err)
        self.assertFalse(self.g.filters)
        rc, out, _ = run("profiles")
        self.assertEqual(self.tsv(out)[0]["filters"], "no")
        rc, out, err = run("filter", "list")  # list works on the old scope
        self.assertEqual(rc, 0, err)

    def test_create_apply_list_delete(self):
        self.scopes(auth.SETTINGS_SCOPE)
        rc, out, err = run("filter", "create", "--from", "news@shop.com", "--archive", "--mark-read",
                           "--add-label", "Promo/Shop", "--apply", "-j")
        self.assertEqual(rc, 0, err)
        r = json.loads(out)[0]
        self.assertEqual(r["criteria"], "from:(news@shop.com)")
        self.assertEqual(r["actions"], "+Promo/Shop,archive,mark-read")
        self.assertEqual(r["applied"], 4)  # n1-n3 + the base m3 from news@shop.com
        self.assertIn("created label Promo/Shop", err)
        m = self.g.box["t"]["messages"]["n1"]
        self.assertNotIn("INBOX", m["labelIds"])
        self.assertNotIn("UNREAD", m["labelIds"])
        rc, out, _ = run("filter", "list")
        self.assertEqual(self.tsv(out)[0]["id"], "F1")
        rc, out, err = run("filter", "delete", "F1")
        self.assertEqual(rc, 0, err)
        self.assertFalse(self.g.filters)
        rc, _, err = run("filter", "create", "--archive")
        self.assertEqual(rc, 2)
        self.assertIn("criterion", err)


if __name__ == "__main__":
    unittest.main()
