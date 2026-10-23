"""Contract tests with mocked HTTP (fixtures recorded from vinted.pt 2026-10-23 by dev/record_fixtures.py).
Run: python3 -m unittest discover -s dev/tests"""
import copy
import io
import json
import re
import shutil
import unittest
import urllib.error
import urllib.parse
from pathlib import Path
from unittest import mock

from support import ROOT, TMP, fixture, run, write_config  # noqa: E402  (sets the test environment first)

from src.api import filters, items, vinted  # noqa: E402
from src.core import http  # noqa: E402
from src.core.errors import Broken, CliError  # noqa: E402


def parse_page(html):
    """Fixture HTML -> the flight object (one chunk '0:{...}')."""
    return json.loads(vinted.flight(html)[2:])


def render(obj):
    text = "0:" + json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return f"<html><body><script>self.__next_f.push([1,{json.dumps(text)}])</script></body></html>"


CATALOG = parse_page(fixture("catalog.html"))
ITEM_ID = str(json.loads(vinted.flight(fixture("item.html"))[2:])["ids"]["item_id"])


def prod(it):
    return it.get("productItem", it)


def item_with(it, iid, price=None):
    it = copy.deepcopy(it)
    p = prod(it)
    p["id"], p["url"] = iid, f"/items/{iid}-x"
    if price is not None:
        for k in ("price", "priceWithDiscount"):
            if p.get(k):
                p[k]["amount"] = f"{price:.2f}"
    return it


def synthetic(params, total=5000):
    """A full page of 96 with unique ids, recycled from the fixture."""
    base = CATALOG["items"]["items"]
    page = int(params["page"])
    obj = copy.deepcopy(CATALOG)
    obj["items"]["items"] = [item_with(base[i % len(base)], 900000000 + page * 1000 + i) for i in range(vinted.PAGE)]
    obj["items"]["pagination"].update(current_page=page, total_entries=total, total_pages=10)
    return render(obj)


class FakeVinted:
    """Replaces core.http.get; routes by URL path."""

    def __init__(self):
        self.calls = []
        self.catalog = copy.deepcopy(CATALOG)
        self.pages = None   # callable(params) -> html, overrides self.catalog
        self.fail = {}      # path -> exception
        self.brand_401 = 0  # answer 401 this many times

    def __call__(self, url, params=None, want="json", headers=None):
        u = urllib.parse.urlparse(url)
        self.calls.append({"host": u.netloc, "path": u.path, "params": dict(params or {}), "want": want,
                           "headers": headers or {}})
        if u.path in self.fail:
            raise self.fail[u.path]
        if u.path == "/catalog":
            assert want == "text"
            return self.pages(params) if self.pages else render(self.catalog)
        m = re.match(r"^/items/(\d+)$", u.path)
        if m:
            assert want == "text"
            if m.group(1) == ITEM_ID:
                return fixture("item.html")
            raise CliError("HTTP 404", status=404)
        if u.path == "/":
            assert want == "cookies"
            return {"access_token_web": "tok", "anon_id": "a"}
        if u.path == "/api/v2/brands":
            assert "access_token_web=tok" in (headers or {}).get("Cookie", "")
            if self.brand_401:
                self.brand_401 -= 1
                raise CliError("HTTP 401", status=401)
            return fixture("brands.json")
        raise AssertionError(f"unrouted {u.path}")

    def paths(self, path):
        return [c for c in self.calls if c["path"] == path]


class Base(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(f"{TMP}/root", ignore_errors=True)
        write_config(site="pt")
        self.fake = FakeVinted()
        p = mock.patch.object(http, "get", self.fake)
        p.start()
        self.addCleanup(p.stop)

    def tsv(self, out):
        lines = out.rstrip("\n").split("\n") if out.strip() else []
        if not lines:
            return []
        head = lines[0].split("\t")
        return [dict(zip(head, ln.split("\t"))) for ln in lines[1:]]

    def searches(self):
        return self.fake.paths("/catalog")


class Search(Base):
    def test_rows(self):
        rc, out, err = run("search", "nike")
        self.assertEqual(rc, 0, err)
        rows = self.tsv(out)
        self.assertEqual(len(rows), len(CATALOG["items"]["items"]))
        self.assertEqual(list(rows[0]), items.ROW_FIELDS)
        r = rows[0]
        self.assertTrue(r["url"].startswith("https://www.vinted.pt/items/"), r)
        self.assertEqual(r["cur"], "EUR")
        self.assertGreater(float(r["total"]), float(r["price"]))  # buyer-protection fee added
        self.assertTrue(r["brand"] and r["cond"])

    def test_flags_to_params(self):
        rc, _, err = run("search", "air max", "--min-price", "5", "--max-price", "40.5", "--sort", "price",
                         "--category", "1242", "--brand", "nike", "--size", "776,777", "--condition",
                         "new-tags,2", "--color", "black,navy", "--currency", "eur")
        self.assertEqual(rc, 0, err)
        p = self.searches()[-1]["params"]
        self.assertEqual((p["search_text"], p["price_from"], p["price_to"], p["currency"]), ("air max", "5", "40.5", "EUR"))
        self.assertEqual((p["order"], p["catalog[]"], p["brand_ids[]"]), ("price_low_to_high", [1242], [53]))
        self.assertEqual((p["size_ids[]"], p["status_ids[]"], p["color_ids[]"]), ([776, 777], [6, 2], [1, 27]))
        self.assertEqual(p["page"], 1)
        self.assertIn("brand 'nike' = Nike (id 53)", err)
        rc, _, _ = run("search", "x")
        self.assertNotIn("order", self.searches()[-1]["params"])  # best = Vinted's relevance default

    def test_category_by_name(self):
        rc, _, err = run("search", "x", "--category", "Homem > Sapatos")
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.searches()[-1]["params"]["catalog[]"], [1231])

    def test_usage_errors(self):
        for argv in (["search"], ["search", "x", "--limit", "961"], ["search", "x", "--limit", "0"],
                     ["search", "x", "--min-price", "9", "--max-price", "1"], ["search", "x", "--site", "zz"],
                     ["search", "x", "--condition", "mint"], ["search", "x", "--color", "rainbow"],
                     ["search", "x", "--category", "nope-nothing"], ["search", "x", "--category", "Sapatilhas"]):
            rc, _, err = run(*argv)
            self.assertEqual(rc, 2, (argv, err))

    def test_paging(self):
        self.fake.pages = synthetic
        rc, out, err = run("search", "x", "--limit", "200")
        self.assertEqual(rc, 0, err)
        self.assertEqual(len(self.tsv(out)), 200)
        self.assertEqual([c["params"]["page"] for c in self.searches()], [1, 2, 3])
        self.assertIn("200 of 5000", err)

    def test_last_page_stops(self):
        rc, out, err = run("search", "x", "--limit", "500")
        self.assertEqual(rc, 0, err)
        self.assertEqual(len(self.searches()), 1)  # short page = the end

    def test_must_filters_titles(self):
        word = prod(CATALOG["items"]["items"][0])["title"].split()[0]
        rc, out, err = run("search", "x", "--must", word)
        self.assertEqual(rc, 0, err)
        rows = self.tsv(out)
        self.assertTrue(rows)
        self.assertTrue(all(word.lower() in r["title"].lower() for r in rows))

    def test_site_option(self):
        rc, _, err = run("search", "x", "--site", "uk")
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.searches()[-1]["host"], "www.vinted.co.uk")
        write_config(site="fr")
        run("search", "x")
        self.assertEqual(self.searches()[-1]["host"], "www.vinted.fr")

    def test_page_change_is_exit_3(self):
        self.fake.catalog = {"something": {"else": []}}
        rc, _, err = run("search", "x")
        self.assertEqual(rc, 3, err)
        self.assertIn("search results", err)
        self.fake.catalog = {"items": {"items": [{"productItem": {"id": 1}}], "pagination": {}}}
        rc, _, err = run("search", "x")
        self.assertEqual(rc, 3, err)
        self.fake.pages = lambda p: "<html><body>no flight</body></html>"
        self.assertEqual(run("search", "x")[0], 3)

    def test_challenge_page_is_exit_3(self):
        self.fake.pages = lambda p: fixture("challenge_403.html")
        rc, _, err = run("search", "x")
        self.assertEqual(rc, 3, err)
        self.assertIn("Cloudflare", err)

    def test_json_fields(self):
        rc, out, err = run("search", "x", "-j")
        self.assertEqual(rc, 0, err)
        row = json.loads(out)[0]
        for k in ("price_value", "total_value", "fee", "promoted", "favourites", "seller_id", "photo"):
            self.assertIn(k, row)


class Show(Base):
    def test_card_by_id(self):
        rc, out, err = run("show", ITEM_ID)
        self.assertEqual(rc, 0, err)
        self.assertTrue(out.startswith("# "))
        for s in ("- price:", "with buyer protection (fee", "- shipping: from", "- brand:", "- seller: test_seller",
                  "- photos (", "## Description", "Recorded fixture", "id 1242"):
            self.assertIn(s, out)

    def test_json(self):
        d = json.loads(run("show", ITEM_ID, "-j")[1])
        self.assertEqual((d["id"], d["category_id"], d["currency"]), (int(ITEM_ID), 1242, "EUR"))
        self.assertAlmostEqual(d["total"], d["price"] + d["buyer_protection"], places=2)
        self.assertNotIn("size_id", d)  # item-page ids are not search filter ids

    def test_by_url_picks_site(self):
        rc, _, err = run("show", f"https://www.vinted.fr/items/{ITEM_ID}-slug-here?referrer=x")
        self.assertEqual(rc, 0, err)
        self.assertEqual([(c["host"], c["path"]) for c in self.fake.calls], [("www.vinted.fr", f"/items/{ITEM_ID}")])

    def test_not_found_and_bad_ref(self):
        rc, _, err = run("show", "123456789")
        self.assertEqual(rc, 2)
        self.assertIn("not found", err)
        self.assertEqual(run("show", "hello")[0], 2)
        self.assertEqual(run("show", "https://example.com/items/123456")[0], 2)
        self.assertEqual(run("show", "https://www.vinted.pt/member/123")[0], 2)

    def test_desc_cut_and_photos(self):
        html = fixture("item.html").replace("Recorded fixture. Worn a few times.", "word " * 1000)
        with mock.patch.object(FakeVinted, "__call__", lambda self, url, params=None, want="json", headers=None: html):
            self.assertIn("(cut: --full)", run("show", ITEM_ID)[1])
            self.assertNotIn("(cut: --full)", run("show", ITEM_ID, "--full")[1])


class Lookups(Base):
    def test_categories(self):
        rc, out, err = run("categories")
        self.assertEqual(rc, 0, err)
        self.assertEqual({r["name"] for r in self.tsv(out)}, {"Mulher", "Homem"})
        rc, out, _ = run("categories", "--under", "Homem")
        self.assertIn("Homem > Sapatos", out)
        rc, out, _ = run("categories", "--grep", "trainers")  # English slug words match too
        self.assertIn("1242", out)
        self.assertEqual(len(self.searches()), 1)  # tree cached

    def test_brands(self):
        rc, out, err = run("brands", "nike", "--limit", "2")
        self.assertEqual(rc, 0, err)
        rows = self.tsv(out)
        self.assertEqual((len(rows), rows[0]["id"], rows[0]["name"]), (2, "53", "Nike"))
        run("brands", "nike")
        self.assertEqual(len(self.fake.paths("/")), 1)  # session cookie cached

    def test_brands_401_refreshes_cookie_once(self):
        self.fake.brand_401 = 1
        self.assertEqual(run("brands", "nike")[0], 0)
        self.assertEqual(len(self.fake.paths("/")), 2)
        self.fake.brand_401 = 2
        self.assertEqual(run("brands", "nike")[0], 1)

    def test_sizes(self):
        rc, out, err = run("sizes", "--category", "1242")
        self.assertEqual(rc, 0, err)
        rows = self.tsv(out)
        self.assertIn("776", [r["id"] for r in rows])
        self.assertEqual(len({r["id"] for r in rows}), len(rows))
        n = len(self.searches())
        self.assertEqual(n, -(-filters.SIZE_MAX // filters.SIZE_CHUNK))
        self.assertTrue(all(len(c["params"]["size_ids[]"]) <= filters.SIZE_CHUNK for c in self.searches()))
        run("sizes", "--category", "1242", "--grep", "38")
        self.assertEqual(len(self.searches()), n)  # cached

    def test_conditions_colors(self):
        rc, out, _ = run("conditions")
        self.assertEqual(self.tsv(out)[0], {"name": "new-tags", "id": "6", "meaning": "new with tags"})
        rc, out, _ = run("colors", "--no-header")
        self.assertIn("navy\t27", out)
        self.assertEqual(self.fake.calls, [])


class Watch(Base):
    def test_add_run_new_and_drop(self):
        rc, out, err = run("watch", "add", "nike", "--brand", "nike", "--max-price", "50", "--name", "shoes")
        self.assertEqual(rc, 0, err)
        self.assertIn("recorded", err)
        saved = json.loads(Path(f"{TMP}/root/watch/searches.json").read_text())["shoes"]
        self.assertEqual((saved["params"]["brand_ids[]"], saved["site"]), ([53], "pt"))
        self.assertEqual(self.searches()[-1]["params"]["order"], "newest_first")
        rc, out, err = run("watch", "run")
        self.assertEqual((rc, out), (0, ""), err)
        self.assertIn("nothing new", err)
        its = self.fake.catalog["items"]["items"]
        target = prod(its[0])
        old = float((target.get("priceWithDiscount") or target["price"])["amount"])
        its[0] = item_with(its[0], target["id"], price=old - 1)
        its.append(item_with(its[1], 111222333))
        rc, out, err = run("watch", "run", "--no-header")
        self.assertEqual(rc, 0, err)
        changes = {ln.split("\t")[2]: ln.split("\t")[1] for ln in out.strip().split("\n")}
        self.assertEqual(changes["111222333"], "new")
        self.assertTrue(changes[str(target["id"])].startswith("drop "))
        self.assertEqual(run("watch", "run")[1], "")  # reported once

    def test_list_rm_unknown(self):
        run("watch", "add", "sofa", "--no-seed")
        rc, out, _ = run("watch", "list")
        self.assertEqual(self.tsv(out)[0]["name"], "sofa")
        self.assertEqual(run("watch", "add", "sofa")[0], 2)
        self.assertEqual(run("watch", "run", "nope")[0], 2)
        self.assertEqual(run("watch", "rm", "sofa")[0], 0)
        self.assertEqual(run("watch", "run")[0], 2)

    def test_category_only_name(self):
        rc, out, err = run("watch", "add", "--category", "1242", "--no-seed")
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.tsv(out)[0]["name"], "cat-1242")

    def test_first_run_after_no_seed_is_baseline(self):
        run("watch", "add", "sofa", "--no-seed")
        rc, out, err = run("watch", "run")
        self.assertEqual((rc, out), (0, ""))
        self.assertIn("baseline", err)

    def test_broken_stops_and_notifies_once(self):
        run("watch", "add", "a", "--no-seed")
        run("watch", "add", "b", "--no-seed")
        self.fake.fail["/catalog"] = Broken("Vinted blocked the request: HTTP 403")
        sent = []

        def fake_run(argv, input=None, **kw):
            sent.append((argv, input))
            return mock.Mock(returncode=0, stderr="")
        with mock.patch("shutil.which", return_value="/bin/claude-tg"), mock.patch("subprocess.run", fake_run):
            rc, out, err = run("watch", "run", "--notify")
            self.assertEqual(rc, 3, err)
            self.assertEqual(len(self.searches()), 1)  # b skipped
            self.assertEqual(len(sent), 1)
            self.assertEqual(sent[0][0][-2:], ["--topic", "vinted"])
            self.assertIn("blocked", sent[0][1])
            run("watch", "run", "--notify")
            self.assertEqual(len(sent), 1)  # same failure within a day: no repeat

    def test_notify_hits_only(self):
        run("watch", "add", "a")
        sent = []
        with mock.patch("shutil.which", return_value="/bin/claude-tg"), \
                mock.patch("subprocess.run", lambda argv, input=None, **kw: sent.append(input) or mock.Mock(returncode=0)):
            run("watch", "run", "--notify")
            self.assertEqual(sent, [])  # nothing new = no message
            its = self.fake.catalog["items"]["items"]
            its.append(item_with(its[-1], 555666777))
            run("watch", "run", "--notify", "--topic", "shop")
        self.assertEqual(len(sent), 1)
        self.assertIn("1 new", sent[0])
        self.assertIn("/items/555666777", sent[0])


class Doctor(Base):
    def test_ok(self):
        rc, out, err = run("doctor")
        self.assertEqual(rc, 0, err)
        self.assertEqual([r["check"] for r in self.tsv(out)], ["site", "search", "brands", "history 30d"])

    def test_blocked(self):
        self.fake.fail["/catalog"] = Broken("blocked")
        rc, out, _ = run("doctor")
        self.assertEqual(rc, 3)
        self.assertIn("search\tno", out)


class Http(unittest.TestCase):
    """core.http.get itself, urlopen mocked."""

    def _resp(self, status, body, ctype, cookies=()):
        if status >= 400:
            return urllib.error.HTTPError("https://www.vinted.pt/catalog", status, "x",
                                          {"Content-Type": ctype}, io.BytesIO(body.encode()))
        r = mock.MagicMock()
        r.__enter__.return_value = r
        r.status, r.read.return_value = status, body.encode()
        r.headers = mock.MagicMock()
        r.headers.get.side_effect = lambda k, d=None: ctype if k == "Content-Type" else d
        r.headers.get_all.return_value = list(cookies)
        return r

    def _get(self, status, body, ctype, want="json", cookies=()):
        resp = self._resp(status, body, ctype, cookies)
        side = resp if isinstance(resp, Exception) else None
        with mock.patch("urllib.request.urlopen", side_effect=side, return_value=resp):
            return http.get("https://www.vinted.pt/catalog", {"search_text": "x", "brand_ids[]": [1, 2]}, want=want)

    def setUp(self):
        shutil.rmtree(f"{TMP}/root", ignore_errors=True)

    def test_challenge_403_is_broken_and_logged(self):
        with self.assertRaises(Broken) as cm:
            self._get(403, fixture("challenge_403.html"), "text/html", want="text")
        self.assertEqual(cm.exception.code, 3)
        self.assertIn("Cloudflare challenge", str(cm.exception))
        counts, last = http.health_stats()
        self.assertEqual(counts, {"blocked": 1})
        self.assertIn("403", last[4])

    def test_html_where_json_expected_is_broken(self):
        with self.assertRaises(Broken):
            self._get(200, "<!DOCTYPE html><html>hi</html>", "text/html")

    def test_404_is_cli_error(self):
        with self.assertRaises(CliError) as cm:
            self._get(404, "<html>gone</html>", "text/html", want="text")
        self.assertEqual((cm.exception.code, cm.exception.status), (1, 404))

    def test_text_cookies_and_log(self):
        self.assertEqual(self._get(200, "<html>ok</html>", "text/html", want="text"), "<html>ok</html>")
        jar = self._get(200, "", "text/html", want="cookies",
                        cookies=["access_token_web=abc; Path=/; HttpOnly", "anon_id=z=1; Secure"])
        self.assertEqual(jar, {"access_token_web": "abc", "anon_id": "z=1"})
        self.assertEqual(http.health_stats()[0], {"ok": 2})

    def test_array_params_and_ua(self):
        resp = self._resp(200, "{}", "application/json")
        with mock.patch("urllib.request.urlopen", return_value=resp) as m:
            http.get("https://www.vinted.pt/x", {"brand_ids[]": [1, 2]})
        req = m.call_args[0][0]
        self.assertIn("brand_ids%5B%5D=1&brand_ids%5B%5D=2", req.full_url)
        self.assertIn("Chrome", req.get_header("User-agent"))
        self.assertEqual(m.call_args[1]["timeout"], http.TIMEOUT)

    def test_tls_context_has_no_post_handshake_auth(self):
        self.assertFalse(http.tls_context().post_handshake_auth)


class Rails(unittest.TestCase):
    def test_commands_never_do_io(self):
        for f in (ROOT / "src" / "commands").rglob("*.py"):
            text = f.read_text()
            self.assertIsNone(re.search(r"urllib|urlopen|http\.get|print\(", text), f)

    def test_only_http_opens_urls(self):
        hits = [f.name for f in (ROOT / "src").rglob("*.py") if "urlopen" in f.read_text()]
        self.assertEqual(hits, ["http.py"])

    def test_no_write_methods(self):
        text = (ROOT / "src" / "core" / "http.py").read_text()
        self.assertIsNone(re.search(r"method=|data=", text))

    def test_top_help(self):
        rc, out, _ = run("--help")
        self.assertEqual(rc, 0)
        for c in ("watch run", "brands", "sizes", "conditions", "colors"):
            self.assertIn(c, out)


if __name__ == "__main__":
    unittest.main()
