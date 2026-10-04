"""migrate against a fake old install, with launchctl / schtasks mocked."""
import io
import os
from contextlib import redirect_stdout
from unittest import mock

import base
import identity
import migrate


class Migrate(base.Case):
    def setUp(self):
        super().setUp()
        self.old = self.tmp / "home" / ".claude" / "task-scheduler"
        (self.old / "tasks").mkdir(parents=True)
        (self.old / "tasks" / "a.yaml").write_text('schedule: "0 9 * * *"\ncommand: echo a\n')
        (self.old / "tasks" / "notes.txt").write_text("not a task")
        r = self.old / "runs" / "a" / "20260101-090000-11"
        r.mkdir(parents=True)
        (r / "meta.json").write_text('{"status": "success"}')
        (r / "output.log").write_text("a\n")
        live = self.old / "runs" / "a" / "20260102-090000-12"
        live.mkdir()
        (live / "meta.json").write_text('{"status": "running"}')
        (self.old / "notify.yaml").write_text("teams: on\n")
        (self.old / "memory.md").write_text("# memory\n")
        (self.old / "memory").mkdir()
        (self.old / "memory" / "x.md").write_text("x\n")
        (self.old / "tasks-xml-cache.bin").write_text("ignored")
        self.snapshot = self.tree(self.old)

    def tree(self, root):
        return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}

    def run_cli(self, *args):
        out = io.StringIO()
        with redirect_stdout(out):
            rc = migrate.main(list(args))
        return rc, out.getvalue()

    def test_copy_dry_run_idempotent_conflict(self):
        rc, out = self.run_cli("--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertIn("+ tasks/a.yaml: would copy", out)
        self.assertFalse(identity.tasks_dir().exists())

        rc, out = self.run_cli()
        self.assertEqual(rc, 0, out)
        new = self.tree(identity.data_dir())
        for rel in ("tasks/a.yaml", "notify.yaml", "memory.md", "memory/x.md",
                    "runs/a/20260101-090000-11/meta.json", "runs/a/20260101-090000-11/output.log"):
            self.assertIn(rel, new)
        self.assertNotIn("tasks/notes.txt", new)
        self.assertNotIn("tasks-xml-cache.bin", new)
        self.assertFalse(any(k.startswith("runs/a/20260102") for k in new))  # still running: skipped
        self.assertIn("still running", out)
        self.assertIn("registered a", out)  # synced
        self.assertEqual(self.tree(self.old), self.snapshot)  # old dir untouched

        rc, out = self.run_cli()
        self.assertEqual(rc, 0, out)
        self.assertIn("0 copied, 6 identical, 0 conflicts", out)

        (identity.data_dir() / "memory.md").write_text("mine\n")
        rc, out = self.run_cli()
        self.assertEqual(rc, 1)
        self.assertIn("! memory.md: differs", out)
        self.assertEqual((identity.data_dir() / "memory.md").read_text(), "mine\n")

    def test_from_and_env(self):
        other = self.tmp / "elsewhere"
        os.rename(self.old, other)
        with self.assertRaises(migrate.NotFound):
            self.run_cli()
        os.environ["TASK_SCHEDULER_HOME"] = str(other)
        self.assertEqual(self.run_cli("--dry-run")[0], 0)
        os.environ.pop("TASK_SCHEDULER_HOME")
        self.assertEqual(self.run_cli("--from", str(other), "--dry-run")[0], 0)
        identity.data_dir().mkdir(parents=True)
        with self.assertRaises(migrate.ValidationError):
            self.run_cli("--from", str(identity.data_dir()))

    def test_retire_launchd(self):
        agents = self.tmp / "home" / "Library" / "LaunchAgents"
        agents.mkdir(parents=True)
        for lbl in ("com.claude.task-scheduler.a", "com.claude.task-scheduler-ui", "com.claude.clockmaster.a", "other"):
            (agents / f"{lbl}.plist").write_text("x")
        calls = []
        with mock.patch.object(identity, "platform", return_value="darwin"), \
                mock.patch.object(migrate, "_run", side_effect=lambda a: calls.append(a) or base.Proc()):
            rc, out = self.run_cli("--dry-run")
            self.assertIn("- launchd agent com.claude.task-scheduler-ui: would remove", out)
            self.assertEqual(calls, [])
            rc, out = self.run_cli()
        self.assertEqual(sorted(p.name for p in agents.iterdir()), ["com.claude.clockmaster.a.plist", "other.plist"])
        self.assertEqual(sorted(c[2].split("/")[-1] for c in calls),
                         ["com.claude.task-scheduler-ui", "com.claude.task-scheduler.a"])

    def test_retire_schtasks(self):
        listing = '"\\claude-task-scheduler\\a","N/A","Ready"\n"\\claude-task-scheduler\\sub\\x","N/A","Ready"\n'
        calls = []

        def fake(argv):
            calls.append(argv)
            return base.Proc(0, listing if "/query" in argv else "")
        with mock.patch.object(identity, "platform", return_value="win32"), \
                mock.patch.object(migrate, "_run", side_effect=fake):
            rc, out = self.run_cli()
        self.assertIn("- Task Scheduler task \\claude-task-scheduler\\a: removed", out)
        self.assertIn(["schtasks", "/delete", "/tn", "\\claude-task-scheduler\\a", "/f"], calls)
        self.assertEqual(len([c for c in calls if "/delete" in c]), 1)


if __name__ == "__main__":
    import unittest
    unittest.main()
