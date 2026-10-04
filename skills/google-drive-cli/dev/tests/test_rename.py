"""profiles --rename: everything keyed by the profile name follows; refusals change nothing."""
import json
import os
import shutil
import unittest
from pathlib import Path
from unittest import mock

from support import TMP, run  # noqa: E402  (sets the test environment first)

from src.api import mounts, persist, service  # noqa: E402
from src.core import paths, profile  # noqa: E402


class Rename(unittest.TestCase):
    def setUp(self):
        base = Path(TMP) / "rename"
        shutil.rmtree(base, ignore_errors=True)
        self.root, self.home, self.cache = base / "root", base / "home", base / "cache"
        self.addCleanup(profile.resolve, "t", "required")  # LIFO: after the env is restored
        env = mock.patch.dict(os.environ, {"GDRIVE_ROOT": str(self.root), "GDRIVE_HOME": str(self.home),
                                           "GDRIVE_CACHE_DIR": str(self.cache)})
        env.start()
        self.addCleanup(env.stop)
        self.svc = {"old": "on"}  # fake index service: profile -> state
        for name, fn in {"state": lambda p: self.svc.get(p, "off"),
                         "remove": lambda p: self.svc.pop(p, None),
                         "install": lambda p: self.svc.__setitem__(p, "on")}.items():
            m = mock.patch.object(service, name, fn)
            m.start()
            self.addCleanup(m.stop)
        self.mounted = set()
        m = mock.patch.object(mounts, "is_mounted", lambda r: r["where"] in self.mounted)
        m.start()
        self.addCleanup(m.stop)
        for n in ("old", "other"):
            (self.root / n / "index").mkdir(parents=True)
            (self.root / n / "config.json").write_text("{}")
            (self.root / n / "rclone.conf").write_text("[gdrive]\n")
        profile.set_default("old")
        self.cdir = paths.sub(self.cache, "old", "abcd1234")
        (self.cdir / "vfsMeta").mkdir()
        (paths.sub(self.home, "logs") / "index-old.log").write_text("tick\n")
        self.rec = {"id": "abcd1234", "profile": "old", "conf": str(self.root / "old" / "rclone.conf"),
                    "where": "/x/gd", "mode": "nfsmount", "pid": None, "cache_dir": str(self.cdir),
                    "path_meta": str(self.cdir / "vfsMeta" / "gdrive"), "persist": None}
        mounts.save(self.rec)
        mounts.save({**self.rec, "id": "ffff0000", "profile": "other", "where": "/x/other",
                     "conf": str(self.root / "other" / "rclone.conf")})

    def test_moves_everything(self):
        rc, out, err = run("profiles", "--rename", "old", "work", "--fields", "profile,default", "--no-header")
        self.assertEqual((rc, out), (0, "other\tno\nwork\tyes\n"), err)
        self.assertIn("1 mount record(s)", err)
        self.assertFalse((self.root / "old").exists())
        self.assertTrue((self.root / "work" / "rclone.conf").exists())
        self.assertEqual(profile.root_config()["default_profile"], "work")
        rec = mounts.load("abcd1234")
        new_cache = str(self.cache / "work" / "abcd1234")
        self.assertEqual((rec["profile"], rec["conf"], rec["cache_dir"], rec["path_meta"]),
                         ("work", str(self.root / "work" / "rclone.conf"), new_cache, new_cache + "/vfsMeta/gdrive"))
        self.assertTrue(Path(new_cache, "vfsMeta").is_dir())
        self.assertEqual(mounts.load("ffff0000")["profile"], "other")  # other profiles untouched
        self.assertEqual(self.svc, {"work": "on"})
        self.assertEqual((self.home / "logs" / "index-work.log").read_text(), "tick\n")
        self.assertFalse((self.home / "logs" / "index-old.log").exists())

    def test_persisted_unit_rewritten(self):
        unit = Path(TMP) / "rename" / "gdrive.mount.abcd1234.plist"
        unit.write_text("old")
        mounts.save({**self.rec, "persist": "launchd", "unit": str(unit)})
        seen = []
        with mock.patch.object(persist, "refresh", lambda r: r), \
                mock.patch.object(persist, "rewrite", lambda r: seen.append((r["profile"], r["conf"]))):
            rc, _, err = run("profiles", "--rename", "old", "work")
        self.assertEqual(rc, 0, err)
        self.assertEqual(seen, [("work", str(self.root / "work" / "rclone.conf"))])

    def test_refusals_change_nothing(self):
        self.mounted.add("/x/gd")
        rc, _, err = run("profiles", "--rename", "old", "work")
        self.assertEqual(rc, 3)
        self.assertIn("/x/gd (mounted)", err)
        self.mounted.clear()
        rc, _, err = run("profiles", "--rename", "old", "other")
        self.assertEqual(rc, 3)
        self.assertIn("already exists", err)
        paths.sub(self.cache, "taken", "x")
        rc, _, _ = run("profiles", "--rename", "old", "taken")
        self.assertEqual(rc, 3)
        (self.root / "old" / "index.lock").write_text(str(os.getppid()))  # a live pid that is not us
        rc, _, err = run("profiles", "--rename", "old", "work")
        self.assertEqual(rc, 3)
        self.assertIn("index update", err)
        (self.root / "old" / "index.lock").unlink()
        rc, _, _ = run("profiles", "--rename", "old", "Bad Name")
        self.assertEqual(rc, 2)
        rc, _, _ = run("profiles", "--rename", "nope", "work")
        self.assertEqual(rc, 2)
        self.assertTrue((self.root / "old" / "config.json").exists())
        self.assertEqual(json.loads((self.home / "mounts" / "abcd1234.json").read_text())["profile"], "old")
        self.assertEqual((self.svc, profile.root_config()["default_profile"]), ({"old": "on"}, "old"))


if __name__ == "__main__":
    unittest.main()
