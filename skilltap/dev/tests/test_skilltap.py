"""skilltap tests: local bare git repos in temp dirs, no network.

Run: python3 -m unittest discover -s dev/tests
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parents[1] / "skilltap.py"
sys.path.insert(0, str(HERE.parents[1]))
import skilltap  # noqa: E402

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
           "GIT_CONFIG_NOSYSTEM": "1"}


def sh(*args, cwd=None):
    r = subprocess.run(list(args), cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        raise AssertionError(f"{args}: {r.stderr}")
    return r.stdout


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="skilltap-test-"))
        self.home = self.tmp / "home"
        self.cfg = self.tmp / "cfg"
        self.home.mkdir()
        self._env = dict(os.environ)
        os.environ.update(GIT_ENV, HOME=str(self.home), CLAUDE_CONFIG_DIR=str(self.cfg),
                          SKILLTAP_GIT_TIMEOUT="20")
        os.environ.pop("XDG_CONFIG_HOME", None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        shutil.rmtree(self.tmp, ignore_errors=True)

    # repo helpers ---------------------------------------------------
    def make_repo(self, name, files):
        work = self.tmp / f"{name}-work"
        bare = self.tmp / f"{name}.git"
        work.mkdir()
        sh("git", "init", "-q", "-b", "main", cwd=work)
        self.write(work, files)
        sh("git", "add", "-A", cwd=work)
        sh("git", "commit", "-qm", "init", cwd=work)
        sh("git", "clone", "-q", "--bare", str(work), str(bare))
        sh("git", "remote", "add", "origin", str(bare), cwd=work)
        sh("git", "fetch", "-q", "origin", cwd=work)
        sh("git", "branch", "-q", "--set-upstream-to=origin/main", cwd=work)
        return work, str(bare)

    def write(self, root, files):
        for rel, body in files.items():
            p = Path(root) / rel
            if body is None:
                p.unlink()
                continue
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body)

    def push(self, work, files, msg="change"):
        self.write(work, files)
        sh("git", "add", "-A", cwd=work)
        sh("git", "commit", "-qm", msg, cwd=work)
        sh("git", "push", "-q", "origin", "main", cwd=work)

    # cli helpers ----------------------------------------------------
    def run_cli(self, *args, env=None):
        """Subprocess run; returns (code, stdout, stderr)."""
        e = dict(os.environ, **(env or {}))
        r = subprocess.run([sys.executable, str(SCRIPT), *args], env=e,
                           capture_output=True, text=True)
        return r.returncode, r.stdout, r.stderr

    def ok(self, *args, **kw):
        code, out, err = self.run_cli(*args, **kw)
        self.assertEqual(code, 0, f"{args}\nstdout: {out}\nstderr: {err}")
        return out

    def call(self, *args):
        """In-process run (lets tests patch internals)."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = skilltap.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def lock(self):
        return json.loads((self.cfg / "skilltap" / "lock.json").read_text())

    def skill(self, name):
        return self.cfg / "skills" / name


SKILL = "---\nname: {name}\ndescription: test\n---\nbody {v}\n"


class TestParse(unittest.TestCase):
    def test_url_forms(self):
        p = skilltap.parse_target
        self.assertEqual(p(["https://github.com/o/r/blob/main/skills/foo/SKILL.md"]),
                         ("https://github.com/o/r.git", "skills/foo/SKILL.md", "main"))
        self.assertEqual(p(["https://github.com/o/r/tree/main/skills/foo/"]),
                         ("https://github.com/o/r.git", "skills/foo", "main"))
        self.assertEqual(p(["https://gitlab.example.com/g/sub/r/-/tree/dev/x"]),
                         ("https://gitlab.example.com/g/sub/r.git", "x", "dev"))
        self.assertEqual(p(["https://github.com/o/r"]), ("https://github.com/o/r.git", "", None))
        self.assertEqual(p(["https://github.com/o/r/tree/main"]), ("https://github.com/o/r.git", "", "main"))
        self.assertEqual(p(["git@github.com:o/r.git", "/a/b/"]), ("git@github.com:o/r.git", "a/b", None))

    def test_same_repo(self):
        s = skilltap.same_repo
        self.assertTrue(s("https://github.com/O/r.git", "git@github.com:o/r"))
        self.assertTrue(s("https://github.com/o/r/", "ssh://git@github.com/o/r.git"))
        self.assertFalse(s("https://github.com/o/r", "https://github.com/o/r2"))


class TestGetRefresh(Base):
    def test_get_subdir_and_name_from_frontmatter(self):
        work, bare = self.make_repo("up", {"skills/foo/SKILL.md": SKILL.format(name="foo-skill", v=1),
                                           "skills/foo/tool.py": "x=1\n",
                                           "skills/foo/__pycache__/tool.cpython-311.pyc": "junk",
                                           "README.md": "r\n"})
        out = self.ok("get", bare, "skills/foo")
        self.assertIn("foo-skill: installed", out)
        self.assertTrue((self.skill("foo-skill") / "tool.py").is_file())
        self.assertFalse((self.skill("foo-skill") / "__pycache__").exists())
        self.assertFalse((self.skill("foo-skill") / "README.md").exists())
        e = self.lock()["skills"]["foo-skill"]
        self.assertEqual((e["path"], e["origin"]), ("skills/foo", "user"))
        # path given as the SKILL.md file works too, and is idempotent
        out = self.ok("get", bare, "skills/foo/SKILL.md")
        self.assertIn("up to date", out)

    def test_repo_root_skill_and_folder_name_fallback(self):
        work, bare = self.make_repo("rootskill", {"SKILL.md": "no frontmatter\n", "a.txt": "a"})
        self.ok("get", bare)
        d = self.skill("rootskill")
        self.assertTrue((d / "a.txt").is_file())
        self.assertFalse((d / ".git").exists())

    def test_refresh_pulls_upstream_change(self):
        work, bare = self.make_repo("up", {"s/SKILL.md": SKILL.format(name="s", v=1)})
        self.ok("get", bare, "s")
        self.push(work, {"s/SKILL.md": SKILL.format(name="s", v=2), "s/new.txt": "n"})
        self.assertIn(" ok", self.ok("status"))                   # status is offline: not fetched yet
        sh("git", "fetch", "-q", cwd=self.ok("where", "s").strip())
        self.assertIn("outdated", self.ok("status"))              # clone behind its fetched upstream
        out = self.ok("refresh", "--quiet")
        self.assertEqual(out.strip(), "skilltap: s updated")
        self.assertIn("body 2", (self.skill("s") / "SKILL.md").read_text())
        self.assertTrue((self.skill("s") / "new.txt").exists())
        self.assertEqual(self.ok("refresh", "--quiet"), "")       # unchanged -> silent
        # --if-older skips a fresh refresh
        self.push(work, {"s/SKILL.md": SKILL.format(name="s", v=3)})
        self.ok("refresh", "--quiet", "--if-older", "24")
        self.assertIn("body 2", (self.skill("s") / "SKILL.md").read_text())
        self.ok("refresh", "--quiet")
        self.assertIn("body 3", (self.skill("s") / "SKILL.md").read_text())
        # file deleted upstream disappears from the installed copy
        self.push(work, {"s/new.txt": None})
        self.ok("refresh", "--quiet")
        self.assertFalse((self.skill("s") / "new.txt").exists())

    def test_local_edits_backed_up_then_restored(self):
        work, bare = self.make_repo("up", {"s/SKILL.md": SKILL.format(name="s", v=1)})
        self.ok("get", bare, "s")
        (self.skill("s") / "SKILL.md").write_text("hacked\n")
        self.assertIn("local edits", self.ok("status"))
        out = self.ok("refresh", "--quiet")
        self.assertIn("local edits saved to", out)
        self.assertIn("body 1", (self.skill("s") / "SKILL.md").read_text())
        backups = list((self.cfg / "skilltap" / "backups").iterdir())
        self.assertEqual((backups[0] / "SKILL.md").read_text(), "hacked\n")

    def test_atomic_swap_keeps_old_copy_when_target_in_use(self):
        work, bare = self.make_repo("up", {"s/SKILL.md": SKILL.format(name="s", v=1)})
        self.ok("get", bare, "s")
        self.push(work, {"s/SKILL.md": SKILL.format(name="s", v=2)})
        target = str(self.skill("s"))
        real = skilltap._rename

        def busy(src, dst):
            if src == target:
                raise PermissionError(13, "in use")
            return real(src, dst)
        skilltap._rename = busy
        try:
            code, out, err = self.call("refresh")
        finally:
            skilltap._rename = real
        self.assertEqual(code, 1)
        self.assertIn("in use", err)
        self.assertIn("body 1", (self.skill("s") / "SKILL.md").read_text())
        staging = self.cfg / "skilltap" / "staging"
        self.assertEqual(list(staging.iterdir()), [])            # no leftovers
        self.assertEqual(sorted(p.name for p in self.skill("s").parent.iterdir()), ["s"])
        code, out, err = self.call("refresh", "--quiet")          # retried next time
        self.assertIn("s updated", out)
        self.assertIn("body 2", (self.skill("s") / "SKILL.md").read_text())

    def test_offline_refresh_is_quiet_and_fast(self):
        work, bare = self.make_repo("up", {"s/SKILL.md": SKILL.format(name="s", v=1)})
        self.ok("get", bare, "s")
        shutil.rmtree(bare)
        code, out, err = self.run_cli("refresh", "--quiet")
        self.assertEqual((code, out), (0, ""))
        self.assertIn("pull failed", err)
        self.assertTrue((self.skill("s") / "SKILL.md").exists())

    def test_untracked_folder_needs_force(self):
        work, bare = self.make_repo("up", {"s/SKILL.md": SKILL.format(name="s", v=1)})
        self.skill("s").mkdir(parents=True)
        (self.skill("s") / "mine.txt").write_text("m")
        code, out, err = self.run_cli("get", bare, "s")
        self.assertEqual(code, 1)
        self.assertIn("not tracked", err)
        self.ok("get", bare, "s", "--force")
        self.assertFalse((self.skill("s") / "mine.txt").exists())
        self.assertTrue(any((self.cfg / "skilltap" / "backups").iterdir()))

    def test_force_switch_drops_orphaned_old_clone(self):
        _, old = self.make_repo("old", {"SKILL.md": SKILL.format(name="s", v=1)})
        _, new = self.make_repo("new", {"x/s/SKILL.md": SKILL.format(name="s", v=2)})
        self.ok("get", old)
        old_src = self.cfg / "skilltap" / "sources" / self.lock()["skills"]["s"]["source"]
        self.assertTrue(old_src.exists())
        code, out, err = self.run_cli("get", new, "x/s")
        self.assertEqual(code, 1)
        self.assertIn("--force switches it", err)
        out = self.ok("get", new, "x/s", "--force")
        self.assertNotIn("local edits", out)                     # untouched copy is not an edit
        self.assertFalse((self.cfg / "skilltap" / "backups").exists())
        self.assertFalse(old_src.exists())
        self.assertIn("body 2", (self.skill("s") / "SKILL.md").read_text())
        self.assertEqual(self.lock()["skills"]["s"]["path"], "x/s")

    def test_forget_and_remove(self):
        work, bare = self.make_repo("up", {"a/SKILL.md": SKILL.format(name="a", v=1),
                                           "b/SKILL.md": SKILL.format(name="b", v=1)})
        self.ok("get", bare, "a")
        self.ok("get", bare, "b")
        self.ok("forget", "a")
        self.assertTrue(self.skill("a").exists())
        self.ok("remove", "b")
        self.assertFalse(self.skill("b").exists())
        self.assertEqual(self.lock()["skills"], {})
        self.assertEqual(list((self.cfg / "skilltap" / "sources").iterdir()), [])  # clean orphan clone dropped
        code, _, err = self.run_cli("remove", "nope")
        self.assertEqual(code, 1)

    def test_status_states_and_where(self):
        work, bare = self.make_repo("up", {"a/SKILL.md": SKILL.format(name="a", v=1),
                                           "b/SKILL.md": SKILL.format(name="b", v=1)})
        self.ok("get", bare, "a")
        self.ok("get", bare, "b")
        shutil.rmtree(self.skill("b"))
        rows = {r["name"]: r for r in json.loads(self.ok("status", "--json"))["skills"]}
        self.assertEqual(rows["a"]["state"], "ok")
        self.assertEqual(rows["b"]["state"], "missing")
        where = self.ok("where", "a").strip()
        self.assertTrue(Path(where, "SKILL.md").is_file())
        self.assertTrue(where.startswith(str(self.cfg / "skilltap" / "sources")))


class TestConfigDir(Base):
    def test_isolation(self):
        work, bare = self.make_repo("up", {"s/SKILL.md": SKILL.format(name="s", v=1)})
        other = self.tmp / "other"
        self.ok("get", bare, "s")
        self.ok("status", env={"CLAUDE_CONFIG_DIR": str(other)})
        self.assertTrue(self.skill("s").exists())
        self.assertFalse((other / "skills" / "s").exists())
        self.assertIn("no tracked skills", self.ok("status", env={"CLAUDE_CONFIG_DIR": str(other)}))
        self.assertFalse((self.home / ".claude").exists())
        # unset -> ~/.claude
        env = dict(os.environ)
        env.pop("CLAUDE_CONFIG_DIR")
        r = subprocess.run([sys.executable, str(SCRIPT), "get", bare, "s"], env=env,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.home / ".claude" / "skills" / "s" / "SKILL.md").exists())


class TestApply(Base):
    def write_list(self, skills):
        p = self.cfg / "baseline" / "skills.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"skills": skills}))
        return str(p)

    def test_apply_add_remove_and_user_protection(self):
        work, bare = self.make_repo("up", {n + "/SKILL.md": SKILL.format(name=n, v=1) for n in "abcdu"})
        self.ok("get", bare, "u")                                  # user's own, also listed
        self.skill("d").mkdir(parents=True)                       # untracked real dir
        (self.skill("d") / "keep").write_text("k")
        spec = {n: {"repo": bare, "path": n} for n in "abdu"}
        lst = self.write_list(spec)
        out = self.ok("apply", lst)
        self.assertIn("a installed (list)", out)
        self.assertIn("b installed (list)", out)
        self.assertNotIn("u ", out)
        locks = self.lock()["skills"]
        self.assertEqual(locks["a"]["origin"], f"list:{lst}")
        self.assertEqual(locks["u"]["origin"], "user")
        self.assertNotIn("d", locks)
        self.assertTrue((self.skill("d") / "keep").exists())
        self.assertIn("d skipped (list): untracked folder", out)  # says why, never touches it
        self.assertEqual(self.ok("apply", lst, "--quiet"), "")     # idempotent, silent under the hook
        # a user skill under a listed name but other source is never touched
        self.ok("get", bare, "c", "--name", "x")
        self.write_list(dict(spec, x={"repo": bare, "path": "a"}))
        self.ok("apply", lst)
        self.assertEqual(self.lock()["skills"]["x"]["path"], "c")
        # drop b and u from the list -> b removed, u (user) kept
        self.write_list({"a": spec["a"]})
        out = self.ok("apply", lst)
        self.assertIn("b removed", out)
        self.assertFalse(self.skill("b").exists())
        self.assertTrue(self.skill("u").exists())
        self.assertIn("u", self.lock()["skills"])
        # refresh --apply with a missing list is a no-op
        self.ok("refresh", "--quiet", "--apply", str(self.tmp / "none.json"))


class TestHook(Base):
    def test_hook_idempotent_and_wrapper(self):
        settings = self.cfg / "settings.json"
        self.cfg.mkdir()
        settings.write_text(json.dumps({"model": "x", "hooks": {"SessionStart": [
            {"matcher": "compact", "hooks": [{"type": "command", "command": "keep-me"}]}]}}))
        self.ok("hook")
        self.ok("hook")
        data = json.loads(settings.read_text())
        cmds = [h["command"] for g in data["hooks"]["SessionStart"] for h in g["hooks"]]
        self.assertEqual(len([c for c in cmds if "skilltap.py" in c]), 1)
        self.assertIn("keep-me", cmds)
        self.assertEqual(data["model"], "x")
        self.assertNotIn("--apply", [c for c in cmds if "skilltap.py" in c][0])
        (self.cfg / "baseline").mkdir()
        (self.cfg / "baseline" / "skills.json").write_text('{"skills": {}}')
        self.ok("hook")
        data = json.loads(settings.read_text())
        cmd = [h["command"] for g in data["hooks"]["SessionStart"] for h in g["hooks"] if "skilltap" in h["command"]]
        self.assertEqual(len(cmd), 1)
        self.assertIn("--apply", cmd[0])
        wrapper = self.home / ".local" / "bin" / ("skilltap.cmd" if os.name == "nt" else "skilltap")
        self.assertIn("skills/skilltap/skilltap.py", wrapper.read_text().replace("\\", "/"))


class TestMigrate(Base):
    def test_migrate(self):
        work, bare = self.make_repo("up", {"a/SKILL.md": SKILL.format(name="a", v=1),
                                           "b/SKILL.md": SKILL.format(name="b", v=1)})
        old = self.cfg / "skillsync"
        sh("git", "clone", "-q", bare, str(old / "repos" / "up"))
        (old / "manifest.json").write_text(json.dumps({"skills": {
            "a": {"repo": bare, "dir": "up", "path": "a"},
            "b": {"repo": bare, "dir": "up", "path": "b"}}}))
        (old / "baseline-state.json").write_text(json.dumps({"installed": ["b"]}))
        for n in "ab":
            shutil.copytree(str(old / "repos" / "up" / n), str(self.skill(n)))
        (self.skill("skillsync")).mkdir()
        (self.cfg / "settings.json").write_text(json.dumps({"hooks": {"SessionStart": [
            {"matcher": "startup", "hooks": [{"type": "command", "command": "python3 x/skills/skillsync/s.py sync"}]},
            {"matcher": "startup", "hooks": [{"type": "command", "command": "python3 baseline/bin/baseline-skills"}]},
            {"matcher": "compact", "hooks": [{"type": "command", "command": "other"}]}]}}))
        bindir = self.home / ".local" / "bin"
        bindir.mkdir(parents=True)
        (bindir / "skillsync").write_text("#!/bin/sh\nexec python3 skills/skillsync/x.py\n")
        out = self.ok("migrate-from-skillsync")
        locks = self.lock()["skills"]
        self.assertEqual(locks["a"]["origin"], "user")
        self.assertEqual(locks["b"]["origin"], f"list:{self.cfg / 'baseline' / 'skills.json'}")
        self.assertFalse(old.exists())
        self.assertFalse(self.skill("skillsync").exists())
        self.assertFalse((bindir / "skillsync").exists())
        self.assertTrue((self.cfg / "skilltap" / "sources" / skilltap.slug(bare) / ".git").exists())
        cmds = [h["command"] for g in json.loads((self.cfg / "settings.json").read_text())["hooks"]["SessionStart"]
                for h in g["hooks"]]
        self.assertEqual(len(cmds), 2)
        self.assertIn("other", cmds)
        self.assertTrue(any("skilltap.py" in c for c in cmds))
        status = self.ok("status")
        self.assertEqual(status.count(" ok"), 2, status)


class TestUpstream(Base):
    """Upstream changes under a tracked clone: list paths ahead of the clone, rewritten history."""

    def setUp(self):
        super().setUp()
        self.work, self.bare = self.make_repo("up", {"clis/foo/SKILL.md": SKILL.format(name="foo", v=1),
                                                     "clis/foo/foo.py": "print(1)\n"})

    def list_file(self, skills):
        p = self.tmp / "list.json"
        p.write_text(json.dumps({"skills": skills}))
        return str(p)

    def test_list_path_ahead_of_clone_pulls_and_switches(self):
        lst = self.list_file({"foo": {"repo": self.bare, "path": "clis/foo"}})
        self.ok("apply", lst)
        sh("git", "mv", "clis/foo", "foo", cwd=self.work)
        self.push(self.work, {"foo/SKILL.md": SKILL.format(name="foo", v=2)}, "move to root")
        lst = self.list_file({"foo": {"repo": self.bare, "path": "foo"}})
        out = self.ok("apply", lst)
        self.assertNotIn("removed", out)
        self.assertEqual(self.lock()["skills"]["foo"]["path"], "foo")
        self.assertIn("body 2", (self.skill("foo") / "SKILL.md").read_text())

    def test_upstream_recreated_resets_clean_clone(self):
        self.ok("get", self.bare, "clis/foo")
        fresh = self.tmp / "fresh"
        fresh.mkdir()
        sh("git", "init", "-q", "-b", "main", cwd=fresh)
        self.write(fresh, {"clis/foo/SKILL.md": SKILL.format(name="foo", v=3),
                           "clis/foo/foo.py": "conflicting\\n",     # replaying old history conflicts
                           })
        sh("git", "add", "-A", cwd=fresh)
        sh("git", "commit", "-qm", "add functionality", cwd=fresh)
        sh("git", "push", "-q", "--force", self.bare, "main", cwd=fresh)
        self.assertIn("body 3", self.ok("refresh") and (self.skill("foo") / "SKILL.md").read_text())
        # rebase can't drop the old history (conflict) -> reset fallback when the clone has no own work
        clone = self.cfg / "skilltap" / "sources" / skilltap.slug(self.bare)
        self.write(fresh, {"clis/foo/SKILL.md": SKILL.format(name="foo", v=4)})
        sh("git", "add", "-A", cwd=fresh)
        sh("git", "commit", "-q", "--amend", "-m", "add functionality", cwd=fresh)
        sh("git", "push", "-q", "--force", self.bare, "main", cwd=fresh)
        real = skilltap.git

        def failing_pull(args, cwd=None, check=True, timeout=None):
            if args[0] == "pull":
                real(["fetch", "--quiet"], cwd=cwd)
                return subprocess.CompletedProcess(args, 1, "", "error: could not apply abc")
            return real(args, cwd=cwd, check=check, timeout=timeout)
        with mock.patch.object(skilltap, "git", failing_pull):
            code, out, err = self.call("refresh")
        self.assertIn("history was rewritten", out)
        self.assertIn("body 4", (self.skill("foo") / "SKILL.md").read_text())

    def test_upstream_recreated_keeps_local_work(self):
        self.ok("get", self.bare, "clis/foo")
        clone = self.cfg / "skilltap" / "sources" / skilltap.slug(self.bare)
        self.write(clone, {"clis/foo/local.md": "mine\n"})
        sh("git", "add", "-A", cwd=clone)
        sh("git", "commit", "-qm", "local", cwd=clone)
        fresh = self.tmp / "fresh"
        fresh.mkdir()
        sh("git", "init", "-q", "-b", "main", cwd=fresh)
        self.write(fresh, {"other/SKILL.md": SKILL.format(name="o", v=1)})
        sh("git", "add", "-A", cwd=fresh)
        sh("git", "commit", "-qm", "x", cwd=fresh)
        sh("git", "push", "-q", "--force", self.bare, "main", cwd=fresh)
        code, out, err = self.run_cli("refresh")
        self.assertEqual(code, 1)
        self.assertIn("pull failed", err)
        self.assertIn("local", sh("git", "log", "--oneline", "-1", cwd=clone))


if __name__ == "__main__":
    unittest.main()
