"""Map pins: geocoding (faked), X-APPLE-STRUCTURED-LOCATION + GEO shape, edit/show. No network."""
import json
import unittest

from support import FakeDav, reset_profile, run  # noqa: E402

from src.api import geo, ics  # noqa: E402

P = "/1234567/calendars/"
# Calendar.app on iPhone, Maps pick (handle shortened)
APPLE = ("X-APPLE-STRUCTURED-LOCATION;VALUE=URI;X-ADDRESS=\"São Mamede, Portugal\";X-APPLE-MAPKIT-HAND\r\n"
         " LE=CAESBBgD;X-APPLE-RADIUS=70.58731954805336;X-APPLE-REFERENCEFRAME=1;X-TITLE=Rua Augusta\r\n"
         "  100:geo:38.711234,-9.137654")
PINNED = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:PIN-123456\r\nSUMMARY:Visit\r\n"
          "DTSTART:20261006T120000Z\r\nDTEND:20261006T130000Z\r\n"
          "LOCATION:Rua Augusta 100\\nSão Mamede\\, Portugal\r\n" + APPLE + "\r\n"
          "GEO:38.711234;-9.137654\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
HIT = [{"lat": "38.7101373", "lon": "-9.1374537", "name": "Rua Augusta",
        "display_name": "Rua Augusta, São Mamede, Lisboa, Lisboa, 1100-053, Portugal",
        "address": {"road": "Rua Augusta", "village": "São Mamede", "town": "Lisboa",
                    "country": "Portugal", "country_code": "pt"},
        "boundingbox": ["38.7086", "38.7117", "-9.1382", "-9.1367"]}]
PHOTON = {"features": [{"geometry": {"coordinates": [-9.3787253, 38.7737135]},
                        "properties": {"name": "Alameda da Fonte Velha", "city": "Sintra (Santa Maria e São Miguel)",
                                       "country": "Portugal", "extent": [-9.38, 38.7747, -9.3774, 38.7727]}}]}


def struct(body):
    ev = ics.parse(body).components("VEVENT")[0]
    return ev, ev.get(geo.STRUCT)


class Base(unittest.TestCase):
    def setUp(self):
        reset_profile()
        self.dav = FakeDav()

    def cli(self, *argv):
        return run(*argv, fake=self.dav)

    def geo_calls(self):
        return [c for c in self.dav.calls if "nominatim" in c["url"] or "photon" in c["url"]]

    def add(self, *extra):
        rc, out, err = self.cli("add", "--title", "Visit", "--start", "2026-10-07 14:00", "--cal", "Work", *extra)
        self.assertEqual(rc, 0, err)
        puts = self.dav.puts()
        self.assertEqual(len(puts), 1)
        return puts[0]["body"], err


class TestAdd(Base):
    def test_geocoded_pin_matches_apple_shape(self):
        self.dav.nominatim = HIT
        body, err = self.add("--location", "Rua Augusta 100, São Mamede")
        self.assertIn("pinned at 38.710137,-9.137454 via OpenStreetMap", err)
        call = self.geo_calls()[0]
        self.assertIn("icloud-calendar/", call["headers"]["User-Agent"])
        self.assertIn("addressdetails=1", call["url"])
        self.assertNotIn("Authorization", call["headers"])
        self.assertTrue(all(len(ln.encode()) <= 75 for ln in body.split("\r\n")))
        ev, p = struct(body)
        _, apple = struct(PINNED)
        self.assertEqual(set(p.params), set(apple.params) - {"X-APPLE-MAPKIT-HANDLE"})
        self.assertEqual(p.params["X-TITLE"], apple.params["X-TITLE"])
        self.assertEqual(p.params["X-ADDRESS"], apple.params["X-ADDRESS"])
        self.assertEqual((p.params["VALUE"], p.params["X-APPLE-REFERENCEFRAME"]), ("URI", "1"))
        self.assertEqual(p.value, "geo:38.710137,-9.137454")
        self.assertEqual(ev.value("GEO"), "38.710137;-9.137454")
        self.assertEqual(ev.text("LOCATION"), "Rua Augusta 100\nSão Mamede, Portugal")
        self.assertIn('X-ADDRESS="São Mamede, Portugal";X-APPLE-RADIUS=', "".join(ics.unfold(body)))

    def test_fuzzy_fallback_and_guard(self):
        self.dav.photon = PHOTON
        body, err = self.add("--location", "Rua Alameda Fonte Velha, Sintra")
        self.assertIn("Photon (fuzzy)", err)
        ev, p = struct(body)
        self.assertEqual((p.params["X-TITLE"], p.params["X-ADDRESS"]), ("Rua Alameda Fonte Velha", "Sintra, Portugal"))
        self.dav = FakeDav()
        self.dav.photon = PHOTON
        body, err = self.add("--location", "Main St 5, Springfield")  # fuzzy hit shares no place word
        self.assertIsNone(struct(body)[1])
        self.assertIn("no map match", err)

    def test_no_hit_and_geocoder_down_keep_plain_text(self):
        for answer in ([], None):
            self.dav = FakeDav()
            self.dav.nominatim = answer
            body, err = self.add("--location", "Room 2")
            ev, p = struct(body)
            self.assertIsNone(p)
            self.assertIsNone(ev.get("GEO"))
            self.assertEqual(ev.text("LOCATION"), "Room 2")
            self.assertIn("without a map pin", err)

    def test_explicit_geo_and_no_geo_skip_lookup(self):
        body, err = self.add("--location", 'Clinic "B": floor 2; door 3, Main St 5', "--geo", "38.7,-9.35")
        self.assertEqual(self.geo_calls(), [])
        ev, p = struct(body)
        self.assertEqual(p.params["X-TITLE"], "Clinic 'B': floor 2; door 3")
        self.assertIn('X-TITLE="Clinic \'B\': floor 2; door 3"', "".join(ics.unfold(body)))
        self.assertEqual(p.value, "geo:38.700000,-9.350000")
        self.assertEqual(ev.text("LOCATION"), 'Clinic "B": floor 2; door 3, Main St 5')
        self.dav = FakeDav()
        body, err = self.add("--location", "Room 2", "--no-geo")
        self.assertEqual(self.geo_calls(), [])
        self.assertIsNone(struct(body)[1])

    def test_geo_needs_location_and_valid_coords(self):
        self.assertEqual(self.cli("add", "--title", "X", "--start", "2026-10-07 14:00", "--geo", "1,2")[0], 2)
        rc, out, err = self.cli("add", "--title", "X", "--start", "2026-10-07 14:00", "--location", "A",
                                "--geo", "91,2")
        self.assertEqual(rc, 2)
        self.assertIn("latitude", err)
        with self.assertRaises(SystemExit) as e:  # argparse: mutually exclusive
            self.cli("add", "--title", "X", "--start", "2026-10-07 14:00", "--location", "A", "--geo", "1,2", "--no-geo")
        self.assertEqual(e.exception.code, 2)


class TestEditShow(Base):
    def setUp(self):
        super().setUp()
        self.dav.add(P + "work/PIN.ics", PINNED, etag='"p1"')

    def edit(self, *extra):
        rc, out, err = self.cli("edit", "PIN-123456", *extra)
        self.assertEqual(rc, 0, err)
        return struct(self.dav.puts()[-1]["body"]), err

    def test_new_location_replaces_pin(self):
        self.dav.nominatim = HIT
        (ev, p), _ = self.edit("--location", "Cafe, São Mamede")
        self.assertNotIn("X-APPLE-MAPKIT-HANDLE", p.params)
        self.assertEqual(p.params["X-TITLE"], "Cafe")
        self.assertEqual(len(ev.all(geo.STRUCT)), 1)

    def test_new_location_without_match_drops_stale_pin(self):
        (ev, p), err = self.edit("--location", "Somewhere else")
        self.assertIsNone(p)
        self.assertIsNone(ev.get("GEO"))
        self.assertEqual(ev.text("LOCATION"), "Somewhere else")

    def test_no_geo_clear_and_repin(self):
        (ev, p), _ = self.edit("--no-geo")
        self.assertIsNone(p)
        self.assertIsNone(ev.get("GEO"))
        self.assertIn("São Mamede", ev.text("LOCATION"))
        self.dav.add(P + "work/PIN.ics", PINNED, etag='"p2"')
        (ev, p), _ = self.edit("--location", "")
        self.assertIsNone(ev.get("LOCATION"))
        self.assertIsNone(p)
        self.dav.add(P + "work/PIN.ics", PINNED, etag='"p3"')
        (ev, p), _ = self.edit("--geo", "38.8,-9.4")
        self.assertEqual(self.geo_calls(), [])
        self.assertEqual((p.value, p.params["X-TITLE"]), ("geo:38.800000,-9.400000", "Rua Augusta 100"))
        self.assertEqual(ev.text("LOCATION"), "Rua Augusta 100\nSão Mamede, Portugal")

    def test_show_map(self):
        rc, out, err = self.cli("show", "PIN-123456")
        self.assertEqual(rc, 0, err)
        self.assertIn("- map: 38.711234,-9.137654 https://maps.apple.com/?ll=38.711234,-9.137654&q=Rua%20Augusta", out)
        d = json.loads(self.cli("show", "PIN-123456", "-j")[1])
        self.assertEqual(d["geo"], "38.711234,-9.137654")


class TestUnits(unittest.TestCase):
    def test_split_and_complete(self):
        self.assertEqual(geo.split("A\nB\nC"), ("A", "B, C"))
        self.assertEqual(geo.split("A, B, C"), ("A", "B, C"))
        self.assertEqual(geo._complete("Pena", "", ["Sintra", "Portugal"]), "Sintra, Portugal")
        self.assertEqual(geo._complete("Rua X", "sao mamede", ["São Mamede", "Portugal"]),
                         "sao mamede, Portugal")

    def test_fold_utf8_roundtrip(self):
        ev = ics.Component("VEVENT")
        geo.put(ev, "x", {"lat": 1.5, "lon": 2.5, "radius": 70, "title": "Шоссе " * 12, "address": "Ç, ü" * 10,
                          "location": "x"})
        text = ics.Component("VCALENDAR", subs=[ev]).serialize()
        self.assertTrue(all(len(ln.encode()) <= 75 for ln in text.split("\r\n")))
        p = ics.parse(text).components("VEVENT")[0].get(geo.STRUCT)
        self.assertEqual(p.params["X-TITLE"], ("Шоссе " * 12).strip())
        self.assertEqual(p.params["X-ADDRESS"], "Ç, ü" * 10)


if __name__ == "__main__":
    unittest.main()
