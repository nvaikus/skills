"""Contract tests with mocked HTTP (fixtures recorded from olx.pt 2026-10-21). Run: python3 -m unittest discover -s dev/tests"""
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

from src.api import offers  # noqa: E402
from src.core import http  # noqa: E402
from src.core.errors import Broken, CliError  # noqa: E402

SEARCH = "/api/v1/offers/"


class FakeOlx:
    """Replaces core.http.get; routes by URL path."""

    def __init__(self):
        self.calls = []
        self.search = fixture("search.json")
        self.pages = None  # callable(params) -> body, overrides self.search
        self.fail = {}     # path -> CliError

    def __call__(self, url, params=None, want="json"):
        u = urllib.parse.urlparse(url)
        self.calls.append({"host": u.netloc, "path": u.path, "params": dict(params or {}), "want": want, "url": url})
        if u.path in self.fail:
            raise self.fail[u.path]
        if want == "bytes":
            assert "olxcdn.com" in u.netloc and ";s=" in url, url
            return b"\xff\xd8jpeg " + url.encode()
        if u.path == SEARCH:
            return self.pages(params) if self.pages else copy.deepcopy(self.search)
        m = re.match(r"^/api/v1/offers/(\d+)/$", u.path)
        if m:
            if m.group(1) in ("674669746", "674668916"):
                return fixture("offer.json")
            raise CliError("HTTP 404", status=404, body=fixture("offer_404.json"))
        if u.path == "/api/v1/offers/metadata/search-categories/":
            return fixture("search_categories.json")
        if u.path == "/api/v1/geo-encoder/location-autocomplete/":
            return fixture("autocomplete.json")
        if u.path == "/api/v1/geo-encoder/regions/":
            return fixture("regions.json")
        if u.path == "/":
            assert want == "text"
            return fixture("home.html")
        if u.path.startswith("/d/"):
            assert want == "text"
            return fixture("ad.html")
        raise AssertionError(f"unrouted {u.path}")

    def searches(self):
        return [c for c in self.calls if c["path"] == SEARCH]


def synthetic_page(params, start_id=900000000):
    """A full organic page: fixture offers recycled with unique ids."""
    base = fixture("search.json")["data"]
    off, lim = int(params["offset"]), int(params["limit"])
    data = []
    for i in range(lim):
        o = copy.deepcopy(base[i % len(base)])
        o["id"] = start_id + off + i
        data.append(o)
    return {"data": data, "metadata": {"visible_total_count": 5000, "source": {"promoted": [], "organic": []}}}


def offer_with(o, oid, price=None):
    o = copy.deepcopy(o)
    o["id"] = oid
    if price is not None:
        for p in o["params"]:
            if p["key"] == "price":
                p["value"].update(value=price, type="price")
    return o


class Base(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(f"{TMP}/root", ignore_errors=True)
        write_config(site="pt")
        self.fake = FakeOlx()
        p = mock.patch.object(http, "get", self.fake)
        p.start()
        self.addCleanup(p.stop)

    def tsv(self, out):
        lines = out.rstrip("\n").split("\n") if out.strip() else []
        if not lines:
            return []
        head = lines[0].split("\t")
        return [dict(zip(head, ln.split("\t"))) for ln in lines[1:]]


class Search(Base):
    def test_rows_drop_promoted(self):
        rc, out, err = run("search", "bicicleta")
        self.assertEqual(rc, 0, err)
        rows = self.tsv(out)
        data = self.fake.search["data"]
        promo = {data[i]["id"] for i in self.fake.search["metadata"]["source"]["promoted"]}
        self.assertEqual(len(rows), len(data) - len(promo))
        self.assertFalse(promo & {int(r["id"]) for r in rows})
        self.assertEqual(list(rows[0]), offers.ROW_FIELDS)
        self.assertIn("promoted skipped", err)

    def test_flags_to_params(self):
        rc, _, err = run("search", "btt", "--min-price", "50", "--max-price", "300", "--sort", "price",
                         "--condition", "used", "--seller", "private", "--region", "Lisboa", "--category", "bicicletas-de-estrada")
        self.assertEqual(rc, 0, err)
        p = self.fake.searches()[-1]["params"]
        self.assertEqual((p["query"], p["filter_float_price:from"], p["filter_float_price:to"]), ("btt", "50", "300"))
        self.assertEqual(p["sort_by"], "filter_float_price:asc")
        self.assertEqual((p["filter_enum_state[0]"], p["owner_type"], p["region_id"], p["category_id"]),
                         ("used", "private", 11, 5425))
        self.assertEqual((p["offset"], p["limit"]), (0, 20))

    def test_city_name_and_distance(self):
        rc, _, err = run("search", "x", "--city", "ericeira", "--distance", "25")
        self.assertEqual(rc, 0, err)
        p = self.fake.searches()[-1]["params"]
        self.assertEqual((p["city_id"], p["distance"]), (11543558, 25))
        self.assertIn("Ericeira", err)

    def test_usage_errors(self):
        for argv in (["search", "x", "--distance", "5"], ["search", "x", "--limit", "201"], ["search"],
                     ["search", "x", "--min-price", "9", "--max-price", "1"], ["search", "x", "--site", "zz"],
                     ["search", "x", "--category", "nope-nothing"], ["search", "x", "--category", "bicicletas-cross-x"]):
            rc, _, err = run(*argv)
            self.assertEqual(rc, 2, (argv, err))

    def test_paging(self):
        self.fake.pages = synthetic_page
        rc, out, err = run("search", "x", "--limit", "120")
        self.assertEqual(rc, 0, err)
        self.assertEqual(len(self.tsv(out)), 120)
        self.assertEqual([(c["params"]["offset"], c["params"]["limit"]) for c in self.fake.searches()],
                         [(0, 50), (50, 50), (100, 20)])

    def test_must_filters_titles(self):
        rc, out, err = run("search", "bicicleta", "--must", "bicicleta")
        self.assertEqual(rc, 0, err)
        rows = self.tsv(out)
        self.assertTrue(rows)
        self.assertTrue(all("bicicleta" in r["title"].lower() for r in rows))

    def test_site_option(self):
        rc, _, err = run("search", "rower", "--site", "pl")
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.fake.searches()[-1]["host"], "www.olx.pl")

    def test_schema_change_is_exit_3(self):
        self.fake.search = {"items": []}
        rc, _, err = run("search", "x")
        self.assertEqual(rc, 3, err)
        self.assertIn("schema changed", err)
        self.fake.search = {"data": [{"id": 1}], "metadata": {}}
        rc, _, err = run("search", "x")
        self.assertEqual(rc, 3, err)

    def test_json_fields(self):
        rc, out, err = run("search", "x", "-j")
        self.assertEqual(rc, 0, err)
        row = json.loads(out)[0]
        for k in ("price_value", "price_kind", "created", "seller", "photos"):
            self.assertIn(k, row)


class Price(unittest.TestCase):
    def _o(self, value):
        return {"params": [{"key": "price", "value": value}] if value is not None else []}

    def test_kinds(self):
        base = {"currency": "EUR", "negotiable": False, "previous_value": None}
        cases = [({**base, "value": 95, "type": "price"}, "95", 95),
                 ({**base, "value": 130, "type": "arranged", "negotiable": True}, "130 neg", 130),
                 ({**base, "value": 0, "type": "exchange"}, "swap", None),
                 ({**base, "value": 0, "type": "free"}, "free", None),
                 ({**base, "value": 0, "type": "budget"}, "ask", None),
                 ({**base, "value": 0.1, "type": "price"}, "0.10", 0.1),
                 (None, "-", None)]
        for value, text, num in cases:
            p = offers.price_of(self._o(value))
            self.assertEqual((p["text"], p["value"]), (text, num), value)


class Show(Base):
    def test_card_by_id(self):
        rc, out, err = run("show", "674669746")
        self.assertEqual(rc, 0, err)
        o = fixture("offer.json")["data"]
        self.assertTrue(out.startswith(f"# {o['title'].strip()}"))
        for s in ("- price:", "- seller:", "- photos:", "## Params", "## Description", o["url"]):
            self.assertIn(s, out)

    def test_by_url_resolves_sku(self):
        rc, _, err = run("show", "https://www.olx.pt/d/anuncio/bicicleta-btwin-IDJEQcI.html")
        self.assertEqual(rc, 0, err)
        self.assertEqual([c["path"] for c in self.fake.calls], ["/d/anuncio/bicicleta-btwin-IDJEQcI.html",
                                                                 "/api/v1/offers/674668916/"])

    def test_not_found_and_bad_ref(self):
        self.assertEqual(run("show", "123456789")[0], 2)
        self.assertEqual(run("show", "hello")[0], 2)
        self.assertEqual(run("show", "https://example.com/x")[0], 2)

    def test_desc_cut(self):
        o = fixture("offer.json")
        o["data"]["description"] = "word " * 1000
        with mock.patch.object(FakeOlx, "__call__", lambda self, url, params=None, want="json": o):
            self.assertIn("(cut: --full)", run("show", "674669746")[1])
            self.assertNotIn("(cut: --full)", run("show", "674669746", "--full")[1])


class Lookups(Base):
    def test_categories_query(self):
        rc, out, err = run("categories", "bicicleta", "--limit", "5")
        self.assertEqual(rc, 0, err)
        rows = self.tsv(out)
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[1]["path"], "desporto-e-lazer/bicicletas")

    def test_categories_tree_cached(self):
        run("categories", "--under", "9")
        rc, out, _ = run("categories", "--grep", "gravel")
        self.assertEqual(rc, 0)
        self.assertIn("5426", out)
        self.assertEqual(sum(1 for c in self.fake.calls if c["path"] == "/"), 1)

    def test_places(self):
        rc, out, err = run("places", "ericeira")
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.tsv(out)[0]["id"], "11543558")
        rc, out, _ = run("places", "--regions")
        self.assertIn("Lisboa", out)


class Watch(Base):
    def test_add_run_new_and_drop(self):
        rc, out, err = run("watch", "add", "bicicleta", "--city", "Ericeira", "--max-price", "500", "--name", "bike")
        self.assertEqual(rc, 0, err)
        self.assertIn("recorded", err)
        saved = json.loads(Path(f"{TMP}/root/watch/searches.json").read_text())["bike"]
        self.assertEqual((saved["params"]["city_id"], saved["site"]), (11543558, "pt"))
        self.assertEqual(self.fake.searches()[-1]["params"]["sort_by"], "created_at:desc")
        rc, out, err = run("watch", "run")
        self.assertEqual((rc, out), (0, ""), err)
        self.assertIn("nothing new", err)
        data = self.fake.search["data"]
        organic = self.fake.search["metadata"]["source"]["organic"]
        target = data[organic[0]]
        old = offers.price_of(target)["value"]
        data[organic[0]] = offer_with(target, target["id"], price=old - 10)
        data.append(offer_with(target, 111222333, price=42))
        self.fake.search["metadata"]["source"]["organic"].append(len(data) - 1)
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

    def test_first_run_after_no_seed_is_baseline(self):
        run("watch", "add", "sofa", "--no-seed")
        rc, out, err = run("watch", "run")
        self.assertEqual((rc, out), (0, ""))
        self.assertIn("baseline", err)

    def test_broken_stops_and_notifies_once(self):
        run("watch", "add", "a", "--no-seed")
        run("watch", "add", "b", "--no-seed")
        self.fake.fail[SEARCH] = Broken("OLX blocked the request: HTTP 403")
        sent = []

        def fake_run(argv, input=None, **kw):
            sent.append((argv, input))
            return mock.Mock(returncode=0, stderr="")
        with mock.patch("shutil.which", return_value="/bin/claude-tg"), mock.patch("subprocess.run", fake_run):
            rc, out, err = run("watch", "run", "--notify")
            self.assertEqual(rc, 3, err)
            self.assertEqual(len(self.fake.searches()), 1)  # b skipped
            self.assertEqual(len(sent), 1)
            self.assertEqual(sent[0][0][-2:], ["--topic", "olx"])
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
            data = self.fake.search["data"]
            data.append(offer_with(data[-1], 555666777))
            self.fake.search["metadata"]["source"]["organic"].append(len(data) - 1)
            run("watch", "run", "--notify", "--topic", "shop")
        self.assertEqual(len(sent), 1)
        self.assertIn("1 new", sent[0])


class Photos(Base):
    def test_download_max_and_paths(self):
        d = f"{TMP}/photos"
        rc, out, err = run("photos", "674669746", "-o", d, "--max", "3")
        self.assertEqual(rc, 0, err)
        rows = [ln.split("\t") for ln in out.strip().split("\n")]
        self.assertEqual(rows[0], ["n", "path", "bytes"])
        self.assertEqual([r[1] for r in rows[1:]], [f"{d}/674669746-0{i}.jpg" for i in (1, 2, 3)])
        self.assertTrue(Path(rows[1][1]).read_bytes().startswith(b"\xff\xd8"))
        cdn = [c for c in self.fake.calls if c["want"] == "bytes"]
        self.assertEqual(len(cdn), 3)
        self.assertTrue(cdn[0]["url"].endswith(";s=1000x1000"))  # the photo's own size, template filled
        data = json.loads(run("photos", "674669746", "-o", d, "-j")[1])
        self.assertEqual(len(data), 8)
        self.assertIn("olxcdn.com", data[0]["url"])
        self.assertEqual(run("photos", "674669746", "--max", "0")[0], 2)
        self.assertEqual(run("photos", "123456789", "-o", d)[0], 2)

    def test_no_photos(self):
        o = fixture("offer.json")
        o["data"]["photos"] = []
        with mock.patch.object(offers.olx, "offer", return_value=o["data"]):
            rc, out, err = run("photos", "674669746", "-o", f"{TMP}/none")
        self.assertEqual((rc, out), (0, "n\tpath\tbytes\n"))
        self.assertIn("no photos", err)

    def test_sheet(self):
        d = f"{TMP}/sheet"
        with mock.patch("shutil.which", return_value=None):
            rc, _, err = run("photos", "674669746", "-o", d, "--sheet")
        self.assertEqual(rc, 2)
        self.assertIn("ffmpeg", err)
        seen = []

        def ff(cmd, **kw):
            seen.append(cmd)
            Path(cmd[-1]).write_bytes(b"sheet")
            return mock.Mock(returncode=0, stderr="")
        with mock.patch("shutil.which", return_value="/usr/bin/ffmpeg"), mock.patch("subprocess.run", ff):
            rc, out, err = run("photos", "674669746", "-o", d, "--max", "5", "--sheet")
        self.assertEqual(rc, 0, err)
        self.assertEqual(out.strip().split("\n")[-1], f"sheet\t{d}/674669746-sheet.jpg\t5")
        self.assertEqual(seen[0].count("-i"), 5)
        self.assertIn("tile=4x2", seen[0][seen[0].index("-filter_complex") + 1])


class Http(unittest.TestCase):
    """core.http.get itself, urlopen mocked."""

    def _resp(self, status, body, ctype):
        if status >= 400:
            return urllib.error.HTTPError("https://www.olx.pt/api/v1/offers/", status, "x",
                                          {"Content-Type": ctype}, io.BytesIO(body.encode()))
        r = mock.MagicMock()
        r.__enter__.return_value = r
        r.status, r.headers, r.read.return_value = status, {"Content-Type": ctype}, body.encode()
        return r

    def _get(self, status, body, ctype):
        resp = self._resp(status, body, ctype)
        side = resp if isinstance(resp, Exception) else None
        with mock.patch("urllib.request.urlopen", side_effect=side, return_value=resp):
            return http.get("https://www.olx.pt/api/v1/offers/", {"query": "x"})

    def setUp(self):
        shutil.rmtree(f"{TMP}/root", ignore_errors=True)

    def test_cloudfront_403_is_broken_and_logged(self):
        with self.assertRaises(Broken) as cm:
            self._get(403, fixture("blocked_403.html"), "text/html")
        self.assertEqual(cm.exception.code, 3)
        self.assertIn("CloudFront", str(cm.exception))
        counts, last = http.health_stats()
        self.assertEqual(counts, {"blocked": 1})
        self.assertIn("403", last[4])

    def test_html_200_is_broken(self):
        with self.assertRaises(Broken):
            self._get(200, "<!DOCTYPE html><html>hi</html>", "text/html")

    def test_400_message(self):
        with self.assertRaises(CliError) as cm:
            self._get(400, json.dumps(fixture("error_400.json")), "application/json")
        self.assertEqual(cm.exception.code, 1)
        self.assertIn("sort_by", str(cm.exception))

    def test_ok_logged(self):
        self.assertEqual(self._get(200, '{"data": []}', "application/json"), {"data": []})
        self.assertEqual(http.health_stats()[0], {"ok": 1})

    def test_bytes(self):
        resp = self._resp(200, "JFIF-data", "image/jpeg")
        with mock.patch("urllib.request.urlopen", return_value=resp):
            self.assertEqual(http.get("https://x.olxcdn.com/v1/files/a/image;s=10x10", want="bytes"), b"JFIF-data")
        resp = self._resp(200, "<!DOCTYPE html><html>wall</html>", "text/html")
        with mock.patch("urllib.request.urlopen", return_value=resp), self.assertRaises(Broken):
            http.get("https://x.olxcdn.com/v1/files/a/image;s=10x10", want="bytes")

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

    def test_top_help(self):
        rc, out, _ = run("--help")
        self.assertEqual(rc, 0)
        self.assertIn("watch run", out)


if __name__ == "__main__":
    unittest.main()
