"""Contract tests with mocked HTTP. Run: python3 -m unittest discover -s dev/tests"""
import copy
import io
import json
import os
import re
import shutil
import subprocess
import time
import unittest
import urllib.error
import urllib.parse
from pathlib import Path
from unittest import mock

from support import ROOT, TMP, fixture, run, write_config  # noqa: E402  (sets the test environment first)

from src.core import http  # noqa: E402
from src.core.errors import CliError  # noqa: E402


def ebay_error(status, error_id, msg="boom"):
    return CliError(f"HTTP {status}", status=status, body={"errors": [{"errorId": error_id, "message": msg}]})


class FakeEbay:
    """Replaces core.http.request; routes by URL path."""

    def __init__(self):
        self.calls = []
        self.tokens = 0
        self.search = fixture("search.json")
        self.fail = {}  # path -> CliError

    def __call__(self, method, url, params=None, form=None, headers=None, allow_mutate=False, basic=None, **kw):
        if method != "GET" and not allow_mutate:
            raise RuntimeError("rail")
        path = urllib.parse.urlparse(url).path
        self.calls.append({"method": method, "path": path, "params": params or {}, "headers": headers or {}})
        if path in self.fail:
            raise self.fail[path]
        if path == "/identity/v1/oauth2/token":
            assert basic == ("app-id-123", "cert-secret-456") and form["grant_type"] == "client_credentials"
            self.tokens += 1
            return {"access_token": f"tok{self.tokens}", "expires_in": 7200, "token_type": "Application Access Token"}
        assert headers["Authorization"].startswith("Bearer tok")
        if path == "/buy/browse/v1/item_summary/search":
            return copy.deepcopy(self.search)
        if path == "/buy/browse/v1/item/get_item_by_legacy_id":
            if params["legacy_item_id"] == "444444444444" and "legacy_variation_id" not in params:
                raise ebay_error(400, 11006, "The legacy ID is invalid. Use itemGroupHref")
            if params["legacy_item_id"] == "999999999999":
                raise ebay_error(400, 11003, "The specified legacy item ID was not found.")
            return fixture("item.json")
        if path.startswith("/buy/browse/v1/item/v1"):
            return fixture("item.json")
        if path == "/buy/browse/v1/item/get_items_by_item_group":
            return fixture("group.json")
        if path == "/commerce/taxonomy/v1/get_default_category_tree_id":
            return {"categoryTreeId": "77"}
        if path == "/commerce/taxonomy/v1/category_tree/77/get_category_suggestions":
            return fixture("categories.json")
        raise AssertionError(f"unrouted {path}")

    def last(self, path):
        return [c for c in self.calls if c["path"] == path][-1]


class Base(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(f"{TMP}/root", ignore_errors=True)
        write_config(market="EBAY_DE", ship_to="PT", done_steps=["account", "keyset", "deletion"])
        self.fake = FakeEbay()
        p = mock.patch.object(http, "request", self.fake)
        p.start()
        self.addCleanup(p.stop)

    def tsv(self, out):
        lines = out.rstrip("\n").split("\n")
        head = lines[0].split("\t")
        return [dict(zip(head, ln.split("\t"))) for ln in lines[1:]]


class TestTop(Base):
    def test_help_and_unknown(self):
        self.assertEqual(run("--help")[0], 0)
        self.assertEqual(run()[0], 2)
        rc, _, err = run("serch")
        self.assertEqual(rc, 2)
        self.assertIn("did you mean: search", err)
        self.assertEqual(run("watch")[0], 2)
        self.assertEqual(run("watch", "ls")[0], 2)
        for cmd in ("setup", "doctor", "search", "item", "categories", "watch add", "watch list", "watch rm", "watch run"):
            rc, out, _ = run(*cmd.split(), "-h")
            self.assertEqual(rc, 0, cmd)
            self.assertIn("usage: ebay", out)


class TestSearch(Base):
    def test_defaults_rows_and_headers(self):
        rc, out, err = run("search", "x1", "carbon")
        self.assertEqual(rc, 0, err)
        rows = self.tsv(out)
        self.assertEqual(list(rows[0]), ["id", "title", "price", "ship", "cond", "buy", "ends", "seller", "url"])
        self.assertEqual(rows[0]["price"], "399.00 EUR")
        self.assertEqual(rows[0]["ship"], "12.90")
        self.assertEqual(rows[0]["buy"], "fixed+offer")
        self.assertEqual(rows[0]["url"], "https://www.ebay.de/itm/111111111111")
        self.assertEqual(rows[0]["seller"], "laptopshop 99.6% (15234)")
        self.assertEqual(rows[1]["price"], "180.50 EUR")  # auction: current bid
        self.assertEqual(rows[1]["buy"], "auction 7b")
        self.assertEqual(rows[1]["ends"], "2026-10-05 18:30Z")
        self.assertEqual(rows[1]["ship"], "free")
        self.assertEqual(rows[1]["title"], "Lenovo X1 Carbon Gen 9")  # tab sanitized
        self.assertEqual(rows[2]["ship"], "?")
        self.assertIn("3 of 1234", err)
        c = self.fake.last("/buy/browse/v1/item_summary/search")
        self.assertEqual(c["params"]["q"], "x1 carbon")
        self.assertEqual(c["params"]["filter"], "deliveryCountry:PT")
        self.assertNotIn("sort", c["params"])
        self.assertEqual(c["headers"]["X-EBAY-C-MARKETPLACE-ID"], "EBAY_DE")
        self.assertEqual(c["headers"]["X-EBAY-C-ENDUSERCTX"], "contextualLocation=country%3DPT")

    def test_filters(self):
        rc, _, err = run("search", "lego", "--min-price", "10", "--max-price", "99.5", "--condition", "new,refurbished",
                         "--buying", "auction,best-offer", "--sort", "price", "--category", "19006", "--location", "de",
                         "--market", "gb", "--ship-to", "pt", "--zip", "1000-001", "--limit", "5")
        self.assertEqual(rc, 0, err)
        c = self.fake.last("/buy/browse/v1/item_summary/search")
        self.assertEqual(c["params"]["filter"], "price:[10..99.5],priceCurrency:GBP,conditionIds:{1000|1500|1750|2000|2010|"
                         "2020|2030|2500},buyingOptions:{AUCTION|BEST_OFFER},deliveryCountry:PT,itemLocationCountry:DE")
        self.assertEqual(c["params"]["sort"], "price")
        self.assertEqual(c["params"]["category_ids"], "19006")
        self.assertEqual(c["params"]["limit"], 5)
        self.assertEqual(c["headers"]["X-EBAY-C-MARKETPLACE-ID"], "EBAY_GB")
        self.assertEqual(c["headers"]["X-EBAY-C-ENDUSERCTX"], "contextualLocation=country%3DPT%2Czip%3D1000-001")
        run("search", "a", "--max-price", "50", "--anywhere", "--sort", "ending")
        c = self.fake.last("/buy/browse/v1/item_summary/search")
        self.assertEqual(c["params"]["filter"], "price:[..50],priceCurrency:EUR")
        self.assertEqual(c["params"]["sort"], "endingSoonest")
        self.assertIn("X-EBAY-C-ENDUSERCTX", c["headers"])  # still priced for PT

    def test_usage_errors(self):
        self.assertEqual(run("search", "a", "--condition", "mint")[0], 2)
        self.assertEqual(run("search", "a", "--buying", "swap")[0], 2)
        self.assertEqual(run("search", "a", "--limit", "500")[0], 2)
        self.assertEqual(run("search")[0], 2)
        self.assertEqual(run("search", "a", "--market", "EBAY_XX")[0], 2)
        self.assertEqual(run("search", "a", "--ship-to", "Portugal")[0], 2)
        write_config()
        rc, _, err = run("search", "a")
        self.assertEqual(rc, 2)
        self.assertIn("no market", err)

    def test_output_modes(self):
        rc, out, _ = run("search", "a", "-j")
        data = json.loads(out)
        self.assertEqual(data[0]["item_id"], "v1|111111111111|0")
        self.assertEqual(data[0]["total"], 411.9)
        self.assertIsNone(data[2]["total"])
        rc, out, _ = run("search", "a", "--fields", "id,price", "--no-header")
        self.assertEqual(out.split("\n")[0], "111111111111\t399.00 EUR")

    def test_empty(self):
        self.fake.search = {"total": 0}
        rc, out, err = run("search", "zzz")
        self.assertEqual(rc, 0)
        self.assertIn("no listings", err)

    def test_rate_limit_and_errors(self):
        self.fake.fail["/buy/browse/v1/item_summary/search"] = ebay_error(429, 2001, "Too many requests")
        rc, _, err = run("search", "a")
        self.assertEqual(rc, 1)
        self.assertIn("rate limit", err)
        self.fake.fail["/buy/browse/v1/item_summary/search"] = ebay_error(400, 12002, "The filter value is invalid")
        rc, _, err = run("search", "a")
        self.assertEqual(rc, 2)
        self.assertIn("errorId 12002", err)


class TestAuth(Base):
    def test_token_cached_and_private(self):
        run("search", "a")
        run("search", "b")
        self.assertEqual(self.fake.tokens, 1)
        p = Path(f"{TMP}/root/token.json")
        if os.name == "posix":
            self.assertEqual(p.stat().st_mode & 0o777, 0o600)
        self.assertNotIn("cert-secret", p.read_text())

    def test_expired_and_revoked(self):
        run("search", "a")
        p = Path(f"{TMP}/root/token.json")
        t = json.loads(p.read_text())
        t["expires_at"] = time.time() + 10  # inside the margin
        p.write_text(json.dumps(t))
        run("search", "a")
        self.assertEqual(self.fake.tokens, 2)
        calls = {"n": 0}
        orig = self.fake.__call__

        def flaky(method, url, **kw):
            if "item_summary" in url and calls["n"] == 0:
                calls["n"] += 1
                raise CliError("HTTP 401", status=401, body={"errors": [{"errorId": 1001, "message": "Invalid access token"}]})
            return orig(method, url, **kw)
        with mock.patch.object(http, "request", flaky):
            rc, _, err = run("search", "a")
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.fake.tokens, 3)

    def test_no_keys_and_rejected(self):
        with mock.patch.dict(os.environ, {"EBAY_CLIENT_ID": "", "EBAY_CLIENT_SECRET": ""}):
            rc, _, err = run("search", "a")
        self.assertEqual(rc, 2)
        self.assertIn("ebay setup", err)
        self.fake.fail["/identity/v1/oauth2/token"] = CliError("HTTP 401", status=401,
                                                              body={"error": "invalid_client", "error_description": "client authentication failed"})
        rc, _, err = run("search", "a")
        self.assertEqual(rc, 2)
        self.assertIn("Sandbox", err)


class TestItem(Base):
    def test_card(self):
        rc, out, err = run("item", "111111111111")
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.fake.last("/buy/browse/v1/item/get_item_by_legacy_id")["params"], {"legacy_item_id": "111111111111"})
        for s in ("# ThinkPad X1", "- price: 399.00 EUR (fixed)", "shipping to PT: 12.90 EUR · DHL Paket International",
                  "arrives 2026-10-08 - 2026-10-12", "returns: accepted, 30 calendar_day, return shipping paid by buyer",
                  "condition: Gebraucht - Small scratch", "seller: laptopshop 99.6% (15234), business",
                  "location: Berlin, 10115, DE", "available: 3, sold 11", "- Marke: Lenovo", "Great laptop\nBattery 90%",
                  "https://i.ebayimg.com/2.jpg", "https://www.ebay.de/itm/111111111111"):
            self.assertIn(s, out)
        self.assertNotIn("x()", out)

    def test_refs(self):
        run("item", "https://www.ebay.de/itm/some-title/111111111111?var=555&hash=x")
        self.assertEqual(self.fake.last("/buy/browse/v1/item/get_item_by_legacy_id")["params"],
                         {"legacy_item_id": "111111111111", "legacy_variation_id": "555"})
        rc, _, _ = run("item", "v1|111111111111|0")
        self.assertEqual(rc, 0)
        self.assertEqual(self.fake.calls[-1]["path"], "/buy/browse/v1/item/v1%7C111111111111%7C0")
        self.assertEqual(run("item", "hello")[0], 2)
        rc, _, err = run("item", "999999999999")
        self.assertEqual(rc, 2)
        self.assertIn("not found", err)

    def test_variations(self):
        rc, out, err = run("item", "444444444444")
        self.assertEqual(rc, 0, err)
        self.assertIn("## Variations (2; card above = cheapest)", out)
        self.assertIn("| id | price | Size |", out)
        self.assertIn("| v1|444444444444|502 | 15.00 EUR | M |", out)
        self.assertIn("- price: 15.00 EUR", out)

    def test_description_cut_and_json(self):
        item = fixture("item.json")
        item["description"] = "x" * 2000
        with mock.patch.object(FakeEbay, "__call__", lambda self, *a, **k: item if "oauth2" not in a[1]
                               else {"access_token": "tok9", "expires_in": 7200}):
            rc, out, _ = run("item", "111111111111")
            self.assertIn("cut at 1500 of 2000", out)
            rc, out, _ = run("item", "111111111111", "--full")
            self.assertNotIn("cut at", out)
            rc, out, _ = run("item", "111111111111", "-j")
            self.assertEqual(json.loads(out)["item_id"], "v1|111111111111|0")


class TestCategories(Base):
    def test_rows(self):
        rc, out, err = run("categories", "laptop")
        self.assertEqual(rc, 0, err)
        rows = self.tsv(out)
        self.assertEqual(rows[0], {"id": "177", "name": "PC Notebooks & Netbooks",
                                   "path": "Computers > Laptops & Netbooks > PC Notebooks & Netbooks"})
        self.assertEqual(self.fake.last("/commerce/taxonomy/v1/get_default_category_tree_id")["params"],
                         {"marketplace_id": "EBAY_DE"})


class TestWatch(Base):
    def test_lifecycle(self):
        rc, out, err = run("watch", "add", "x1 carbon", "--max-price", "450", "--condition", "used")
        self.assertEqual(rc, 0, err)
        self.assertIn("3 current items recorded", err)
        self.assertEqual(self.tsv(out)[0]["name"], "x1-carbon")
        c = self.fake.last("/buy/browse/v1/item_summary/search")
        self.assertEqual(c["params"]["sort"], "newlyListed")
        self.assertEqual(c["params"]["limit"], 50)
        self.assertEqual(run("watch", "add", "x1 carbon")[0], 2)  # duplicate name
        rc, out, err = run("watch", "run")
        self.assertEqual((rc, out), (0, ""))
        self.assertIn("nothing new", err)
        s = self.fake.search["itemSummaries"]
        s[0]["price"]["value"] = "349.00"          # fixed price drop
        s[1]["currentBidPrice"]["value"] = "100"    # auction bid changes are never "drops"
        s.append({**copy.deepcopy(s[2]), "itemId": "v1|555555555555|0", "legacyItemId": "555555555555", "title": "New one"})
        rc, out, err = run("watch", "run")
        rows = self.tsv(out)
        self.assertEqual([(r["change"], r["id"]) for r in rows], [("drop 399.00>349.00", "111111111111"), ("new", "555555555555")])
        self.assertEqual(rows[0]["watch"], "x1-carbon")
        self.assertEqual(run("watch", "run")[1], "")  # reported once
        rc, out, _ = run("watch", "list")
        self.assertEqual(self.tsv(out)[0]["flags"], "--max-price 450.0 --condition used")
        self.assertEqual(self.tsv(out)[0]["seen"], "4")
        self.assertEqual(run("watch", "rm", "x1-carbon")[0], 0)
        self.assertEqual(run("watch", "run")[0], 2)

    def test_no_seed_and_failure(self):
        run("watch", "add", "a", "--no-seed")
        run("watch", "add", "b", "--no-seed", "--market", "EBAY_GB")
        rc, out, err = run("watch", "run")
        self.assertEqual((rc, out), (0, ""))
        self.assertIn("first run, 3 current items recorded as baseline", err)
        self.fake.search["itemSummaries"].append({**copy.deepcopy(self.fake.search["itemSummaries"][2]),
                                                  "itemId": "v1|6|0", "legacyItemId": "666666666666"})
        orig = self.fake.__call__

        def gb_fails(method, url, headers=None, **kw):
            if "item_summary" in url and headers.get("X-EBAY-C-MARKETPLACE-ID") == "EBAY_GB":
                raise ebay_error(500, 10001, "internal")
            return orig(method, url, headers=headers, **kw)
        with mock.patch.object(http, "request", gb_fails):
            rc, out, err = run("watch", "run")
        self.assertEqual(rc, 1)
        self.assertEqual([r["watch"] for r in self.tsv(out)], ["a"])
        self.assertIn("watch b failed", err)


class TestSetup(Base):
    def test_walk(self):
        write_config()
        rc, out, _ = run("setup")
        self.assertEqual(rc, 5)
        self.assertTrue(out.startswith("WAITING account"))
        self.assertIn("ebay setup --done account", out)
        run("setup", "--done", "account")
        rc, out, _ = run("setup", "--done", "keyset")
        self.assertIn("WAITING deletion", out)
        self.assertIn("Not persisting eBay data", out)
        with mock.patch.dict(os.environ, {"EBAY_CLIENT_ID": "", "EBAY_CLIENT_SECRET": ""}):
            rc, out, _ = run("setup", "--done", "deletion")
            self.assertIn("WAITING keys", out)
            rc, _, err = run("setup", "--keys-stdin", stdin="app-id-123\ncert-secret-456\n")
            p = Path(f"{TMP}/root/credentials.json")
            if os.name == "posix":
                self.assertEqual(p.stat().st_mode & 0o777, 0o600)
            self.assertIn("WAITING defaults", err + run("setup")[1])
            rc, out, _ = run("setup", "--market", "de", "--ship-to", "pt")
            self.assertEqual(rc, 0, out)
            self.assertTrue(out.startswith("DONE"))
            self.assertIn("EBAY_DE", out)
            self.assertEqual(json.loads(Path(f"{TMP}/root/config.json").read_text())["ship_to"], "PT")
            rc, out, _ = run("doctor")
            self.assertEqual(rc, 0, out)
            self.assertIn("file: App ID app-i... (10 chars)", out)
            self.assertNotIn("cert-secret", out)

    def test_rejected_keys(self):
        self.fake.fail["/identity/v1/oauth2/token"] = CliError("HTTP 401", status=401, body={"error": "invalid_client"})
        rc, out, _ = run("setup")
        self.assertEqual(rc, 5)
        self.assertIn("WAITING keys-rejected", out)
        rc, out, _ = run("doctor")
        self.assertEqual(rc, 1)
        self.assertIn("token\tno", out)

    def test_bad_keys_stdin(self):
        self.assertEqual(run("setup", "--keys-stdin", stdin="only-one\n")[0], 2)
        self.assertEqual(run("setup", "--keys-stdin", stdin="same\nsame\n")[0], 2)


class TestHttp(unittest.TestCase):
    def test_429_retry_after_then_ok(self):
        resp = mock.MagicMock()
        resp.__enter__.return_value.read.return_value = b'{"ok": 1}'
        err = urllib.error.HTTPError("u", 429, "Too Many", {"Retry-After": "0"}, io.BytesIO(b'{"errors": []}'))
        with mock.patch("urllib.request.urlopen", side_effect=[err, resp]), mock.patch("time.sleep") as sl:
            self.assertEqual(http.request("GET", "https://api.ebay.com/x"), {"ok": 1})
        sl.assert_called_once_with(0.0)

    def test_long_retry_after_not_slept(self):
        err = urllib.error.HTTPError("u", 429, "Too Many", {"Retry-After": "3600"}, io.BytesIO(b"{}"))
        with mock.patch("urllib.request.urlopen", side_effect=[err]), mock.patch("time.sleep") as sl:
            with self.assertRaises(CliError) as cm:
                http.request("GET", "https://api.ebay.com/x")
        self.assertEqual(cm.exception.status, 429)
        sl.assert_not_called()

    def test_rail(self):
        with self.assertRaises(RuntimeError):
            http.request("POST", "https://api.ebay.com/x")


class TestRails(unittest.TestCase):
    def test_commands_never_speak_http(self):
        out = subprocess.run(["grep", "-rnE", r"http\.request|allow_mutate|urllib|print\(", str(ROOT / "src" / "commands")],
                             capture_output=True, text=True).stdout
        self.assertEqual(out, "")

    def test_no_personal_data(self):
        pat = re.compile("/Use" + r"rs/|/ho" + r"me/[a-z]|@gm" + r"ail\.com|192\.168\.|100\.\d+\.\d+\.\d+|skills-" + "private")
        for p in ROOT.rglob("*"):
            if p.is_file() and p.suffix in (".py", ".md", ".json", ".cmd") and "__pycache__" not in p.parts:
                self.assertIsNone(pat.search(p.read_text(encoding="utf-8")), p)


if __name__ == "__main__":
    unittest.main()
