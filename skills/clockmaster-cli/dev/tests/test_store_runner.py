import json
import os
import subprocess
import sys
import time

import base
import runner
import store
import taskdef


def meta_of(name):
    return store.recent(name, 1)[0]


class Runner(base.Case):
    def test_catchup_false_drops_late_scheduled_start(self):
        from datetime import datetime
        from unittest import mock
        self.write_task("nc", 'schedule: "0 21 * * *"\ncommand: echo hi\ncatchup: false\n')
        t = taskdef.load("nc")
        self.assertTrue(taskdef.on_time(t, datetime(2026, 10, 4, 21, 2, 30)))
        self.assertFalse(taskdef.on_time(t, datetime(2026, 10, 5, 7, 14)))
        with mock.patch.object(runner, "datetime") as dt:
            dt.now.return_value = datetime(2026, 10, 5, 7, 14)
            self.assertEqual(runner.exec_task("nc", "schedule"), 0)
        self.assertEqual(store.recent("nc", 5), [])               # dropped, not recorded
        self.assertEqual(runner.exec_task("nc"), 0)               # manual runs are never dropped
        self.assertEqual(meta_of("nc")["status"], "success")
        self.write_task("cu", 'schedule: "0 21 * * *"\ncommand: echo hi\n')
        self.assertTrue(taskdef.load("cu").catchup)

    def test_success_records_output_and_env(self):
        self.write_task("ok", 'schedule: "0 9 * * *"\ncommand: echo out; echo err >&2; echo "sid=$TASK_SESSION_ID term=$TERM"\n')
        self.assertEqual(runner.exec_task("ok"), 0)
        m = meta_of("ok")
        self.assertEqual((m["status"], m["exitCode"], m["trigger"]), ("success", 0, "manual"))
        log = (store.run_dir("ok", m["runId"]) / "output.log").read_text()
        self.assertEqual(log, f"out\nerr\nsid={m['sessionId']} term=dumb\n")  # no shell-init noise

    def test_exit_inside_command_keeps_rc_and_clean_log(self):
        self.write_task("bad", 'schedule: "0 9 * * *"\ncommand: echo x; exit 3\n')
        self.assertEqual(runner.exec_task("bad"), 1)
        m = meta_of("bad")
        self.assertEqual((m["status"], m["exitCode"]), ("failed", 3))
        self.assertEqual((store.run_dir("bad", m["runId"]) / "output.log").read_text(), "x\n")

    def test_timeout(self):
        self.write_task("slow", 'schedule: "0 9 * * *"\ncommand: sleep 30\ntimeout: 1s\n')
        t0 = time.monotonic()
        self.assertEqual(runner.exec_task("slow"), 124)
        self.assertLess(time.monotonic() - t0, 15)
        self.assertEqual(meta_of("slow")["status"], "timeout")

    def test_missing_workdir(self):
        self.write_task("w", 'schedule: "0 9 * * *"\ncommand: true\nworkdir: /nonexistent/dir\n')
        self.assertEqual(runner.exec_task("w"), 1)
        self.assertEqual(meta_of("w")["exitCode"], 78)

    def test_keep_prunes(self):
        self.write_task("k", 'schedule: "0 9 * * *"\ncommand: true\nkeep: 2\n')
        for i in range(3):
            d = store.run_dir("k", f"20200101-00000{i}-1")
            d.mkdir(parents=True)
            store.write(d, {"runId": d.name, "status": "success", "start": "2020-01-01T00:00:00+00:00", "pid": 1})
        runner.exec_task("k")
        self.assertEqual(len(store.run_dirs("k")), 2)


class Reconcile(base.Case):
    def test_dead_runner_becomes_killed(self):
        d = store.run_dir("t", "20260101-000000-999999")
        d.mkdir(parents=True)
        p = subprocess.Popen(["true"])
        p.wait()
        store.write(d, {"runId": d.name, "status": "running", "start": store.iso(store.now()), "pid": p.pid, "pgid": None})
        (d / "output.log").write_text("partial\n")
        m = store.read(d)
        self.assertEqual((m["status"], m["exitCode"]), ("killed", None))
        self.assertIsNotNone(m["end"])
        self.assertEqual(json.loads((d / "meta.json").read_text())["status"], "killed")

    def test_foreign_pid_is_not_our_runner(self):
        d = store.run_dir("t", "20260101-000000-1")
        d.mkdir(parents=True)
        store.write(d, {"runId": d.name, "status": "running", "start": store.iso(store.now()), "pid": os.getpid()})
        # the test process is alive but its cmdline is not `clockmaster ... t`
        self.assertEqual(store.read(d)["status"], "killed")


class Stop(base.Case):
    def test_stop_live_run(self):
        self.write_task("long", 'schedule: "0 9 * * *"\ncommand: sleep 30\n')
        entry = str(base.identity.ENTRY)
        env = dict(os.environ)
        proc = subprocess.Popen([sys.executable, entry, "run", "long", "--quiet"], env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.time() + 10
            while time.time() < deadline:
                dirs = store.run_dirs("long")
                if dirs and (store.read_raw(dirs[0]) or {}).get("pgid"):
                    break
                time.sleep(0.1)
            self.assertEqual(store.read(store.run_dirs("long")[0])["status"], "running")
            rdir = store.pick_to_stop("long")
            meta, note = store.stop(rdir)
            self.assertEqual(meta["status"], "stopped", note)
            proc.wait(timeout=10)
            time.sleep(0.2)
            self.assertEqual(store.read(rdir)["status"], "stopped")  # the runner did not overwrite it
            meta2, note2 = store.stop(rdir)
            self.assertIn("nothing to stop", note2)
        finally:
            if proc.poll() is None:
                proc.kill()


if __name__ == "__main__":
    import unittest
    unittest.main()
