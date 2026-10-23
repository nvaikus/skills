"""Opt-in live smoke test against real Vinted: VINTED_LIVE=1 python3 -m unittest discover -s dev/tests -p test_live.py
Proves the pages and the brands API still carry the data this CLI reads (exit 3 = it broke)."""
import os
import unittest

from support import run  # noqa: E402

LIVE = os.environ.get("VINTED_LIVE") == "1"


@unittest.skipUnless(LIVE, "set VINTED_LIVE=1 for the live smoke test")
class Live(unittest.TestCase):
    def test_search_show_lookups(self):
        os.environ["VINTED_GAP"] = "1.5"
        rc, out, err = run("search", "nike", "--brand", "nike", "--max-price", "40", "--limit", "3", "--sort", "newest")
        self.assertEqual(rc, 0, err)
        lines = out.strip().split("\n")
        self.assertEqual(lines[0].split("\t")[:3], ["id", "price", "total"])
        self.assertGreaterEqual(len(lines), 2)
        rc, out, err = run("show", lines[1].split("\t")[0])
        self.assertEqual(rc, 0, err)
        self.assertIn("with buyer protection", out)
        rc, out, err = run("categories", "--grep", "trainers")
        self.assertEqual(rc, 0, err)
        self.assertIn("1242", out)


if __name__ == "__main__":
    unittest.main()
