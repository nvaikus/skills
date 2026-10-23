"""Opt-in live smoke test against the real OLX endpoint: OLX_LIVE=1 python3 -m unittest test_live
Proves the endpoint still answers JSON in the shape this CLI reads (exit 3 = it broke)."""
import os
import unittest

from support import run  # noqa: E402

LIVE = os.environ.get("OLX_LIVE") == "1"


@unittest.skipUnless(LIVE, "set OLX_LIVE=1 for the live smoke test")
class Live(unittest.TestCase):
    def test_search_show_categories(self):
        os.environ["OLX_GAP"] = "1"
        rc, out, err = run("search", "bicicleta", "--limit", "3", "--sort", "newest")
        self.assertEqual(rc, 0, err)
        lines = out.strip().split("\n")
        self.assertEqual(lines[0].split("\t")[:3], ["id", "price", "cur"])
        self.assertGreaterEqual(len(lines), 2)
        ad = lines[1].split("\t")[0]
        rc, out, err = run("show", ad)
        self.assertEqual(rc, 0, err)
        self.assertIn("- price:", out)
        rc, out, err = run("categories", "bicicleta", "--limit", "3")
        self.assertEqual(rc, 0, err)
        self.assertIn("bicicletas", out)


if __name__ == "__main__":
    unittest.main()
