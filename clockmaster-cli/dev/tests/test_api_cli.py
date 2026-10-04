"""HTTP API against a threaded server on a free port (null backend), the CLI
in-process, and the entry script as a real subprocess."""
import io
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import redirect_stderr, redirect_stdout
from datetime import timedelta
from urllib.parse import quote
from http.server import ThreadingHTTPServer

import base
import cli
import identity
import store
from web import server

TASK = 'schedule: "0 9 * * 1-5"\ncommand: echo hi\ngroup: reports\n'


class Api(base.Case):
    def setUp(self):
        super().setUp()
        self.write_task("rep", TASK)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        super().tearDown()

    def call(self, method, path, body=None):
        req = urllib.request.Request(self.base + path, method=method,
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                raw, status, ctype = r.read(), r.status, r.headers["Content-Type"]
        except urllib.error.HTTPError as e:
            raw, status, ctype = e.read(), e.code, e.headers["Content-Type"]
        return status, (json.loads(raw) if ctype.startswith("application/json") else raw.decode())

    def test_app_and_tasks(self):
        st, app = self.call("GET", "/api/app")
        self.assertEqual(st, 200)
        self.assertEqual(set(app), {"app", "platform", "backend", "dataDir", "notes", "sounds", "canOpenTerminal", "notifyChannels"})
        self.assertEqual(app["backend"], "null")
        st, tasks = self.call("GET", "/api/tasks")
        t = tasks[0]
        for key in ("name", "group", "description", "enabled", "notify", "sound", "schedule", "scheduleText",
                    "command", "workdir", "timeoutSec", "keep", "state", "drift", "nextRun", "lastRun", "lastRuns"):
            self.assertIn(key, t)
        self.assertEqual((t["scheduleText"], t["group"], t["state"], t["drift"]),
                         ("every weekday at 9:00", "reports", "missing", True))
        st, one = self.call("GET", "/api/tasks/rep")
        self.assertEqual(one["yaml"], TASK)
        self.assertEqual(self.call("GET", "/api/tasks/nope")[0], 404)

    def test_schedule_preview(self):
        st, out = self.call("GET", "/api/schedule?cron=" + urllib.parse.quote(" */15  8-19 * * * "))
        self.assertEqual(st, 200)
        self.assertEqual((out["cron"], out["text"]), ("*/15 8-19 * * *", "every 15 minutes from 8:00 to 19:59"))
        self.assertEqual(len(out["next"]), 3)
        self.assertLess(out["next"][0], out["next"][1])
        st, out = self.call("GET", "/api/schedule?cron=30+*+*+*+*")
        self.assertEqual(out["text"], "every hour at :30")
        st, out = self.call("GET", "/api/schedule?cron=61+*+*+*+*")
        self.assertEqual(st, 400)
        self.assertIn("out of range", out["error"])
        self.assertEqual(self.call("GET", "/api/schedule")[0], 400)

    def test_edit_validation_and_sync(self):
        st, out = self.call("POST", "/api/tasks/rep", {"schedule": "bad"})
        self.assertEqual(st, 400)
        self.assertIn("5 cron fields", out["error"])
        self.assertNotIn("rep.yaml", out["error"])
        st, out = self.call("POST", "/api/sync")
        self.assertTrue(out["ok"])
        st, out = self.call("POST", "/api/tasks/rep/enabled", {"enabled": False})
        self.assertEqual((st, out["enabled"]), (200, False))
        self.write_task("other", TASK)
        self.assertEqual(self.call("POST", "/api/tasks/rep", {"name": "other"})[0], 409)

    def test_run_log_resume_overview_timeline(self):
        self.assertEqual(self.call("POST", "/api/tasks/rep/run")[0], 202)
        deadline = time.time() + 15
        while time.time() < deadline:
            runs = self.call("GET", "/api/tasks/rep/runs")[1]
            if runs and runs[0]["status"] != "running":
                break
            time.sleep(0.2)
        run = runs[0]
        self.assertEqual((run["status"], run["exitCode"], run["trigger"], run["hasSession"]), ("success", 0, "manual", False))
        self.assertEqual(self.call("GET", f"/api/tasks/rep/runs/{run['runId']}/log")[1], "hi\n")
        st, info = self.call("GET", f"/api/tasks/rep/runs/{run['runId']}/resume")
        self.assertEqual((st, info["canOpen"]), (200, False))
        self.assertIn("claude --resume", info["command"])
        st, res = self.call("POST", f"/api/tasks/rep/runs/{run['runId']}/resume")
        self.assertEqual((res["opened"], res["command"]), (False, info["command"]))
        strip = self.call("GET", "/api/tasks")[1][0]["lastRuns"]
        self.assertEqual(strip, [{"runId": run["runId"], "status": "success", "start": run["start"],
                                  "durationSec": run["durationSec"], "trigger": "manual"}])
        st, dr = self.call("GET", "/api/drift")
        self.assertEqual((st, dr), (200, {"drift": 1}))
        st, tl = self.call("GET", "/api/timeline?from=2026-01-01T00:00:00Z&to=2030-01-01T00:00:00Z")
        self.assertEqual(st, 200)
        self.assertLessEqual(len(tl[0]["planned"]), 1000)
        self.assertEqual(tl[0]["plannedEvery"], 1)
        self.assertEqual(tl[0]["avgDurationSec"], run["durationSec"])

    def test_planned_sampled_across_window(self):
        self.write_task("rep", 'schedule: "* * * * *"\ncommand: echo hi\n')
        now = store.now()
        frm, to = store.iso(now), store.iso(now + timedelta(days=7))
        tl = self.call("GET", f"/api/timeline?from={quote(frm)}&to={quote(to)}")[1]
        lane = tl[0]
        self.assertTrue(lane["plannedTruncated"])
        self.assertEqual(lane["plannedEvery"], 11)  # 10080 starts / 1000, rounded up
        self.assertLessEqual(len(lane["planned"]), 1000)
        # the samples reach the end of the window, not just its first 1000 minutes
        self.assertGreater(store.stamp(lane["planned"][-1]), now + timedelta(days=6, hours=23))

    def test_avg_duration(self):
        self.assertIsNone(self.call("GET", "/api/tasks")[1][0]["avgDurationSec"])
        for i, (st, d) in enumerate([("success", 2.0), ("failed", 4.0), ("timeout", 99.0), ("stopped", 50.0), ("skipped", 0)]):
            self.seed_run("rep", f"20261002-18300{i}-111", st)
            m = store.read(store.run_dir("rep", f"20261002-18300{i}-111"))
            store.write(store.run_dir("rep", f"20261002-18300{i}-111"), {**m, "durationSec": d})
        self.assertEqual(self.call("GET", "/api/tasks")[1][0]["avgDurationSec"], 3.0)
        tl = self.call("GET", "/api/timeline?from=2026-01-01T00:00:00Z&to=2026-01-02T00:00:00Z")[1]
        self.assertEqual(tl[0]["avgDurationSec"], 3.0)

    def seed_run(self, task, run_id, status="success"):
        d = store.run_dir(task, run_id)
        d.mkdir(parents=True)
        store.write(d, {"runId": run_id, "status": status, "start": "2026-10-02T18:30:00+00:00",
                        "durationSec": 1.5, "trigger": "schedule"})

    def test_run_search(self):
        self.write_task("other", TASK)
        self.seed_run("rep", "20261002-183000-111")
        self.seed_run("rep", "20261001-090000-222", "failed")
        self.seed_run("other", "20261002-120000-333")
        self.seed_run("gone", "20261002-190000-444")  # no task file: excluded
        st, out = self.call("GET", "/api/runs/search?q=20261002")
        self.assertEqual(st, 200)
        self.assertEqual([(r["task"], r["runId"]) for r in out],
                         [("rep", "20261002-183000-111"), ("other", "20261002-120000-333")])
        self.assertEqual(set(out[0]), {"task", "runId", "status", "start", "durationSec"})
        self.assertEqual((out[0]["status"], out[0]["durationSec"]), ("success", 1.5))
        out = self.call("GET", "/api/runs/search?q=0900")[1]
        self.assertEqual([(r["runId"], r["status"]) for r in out], [("20261001-090000-222", "failed")])
        self.assertEqual(len(self.call("GET", "/api/runs/search?q=2026&limit=2")[1]), 2)
        self.assertEqual(self.call("GET", "/api/runs/search?q=zz-nothing")[1], [])
        self.assertEqual(self.call("GET", "/api/runs/search?q=444")[1], [])
        self.assertEqual(self.call("GET", "/api/runs/search?q=")[1], [])

    def test_run_search_case_insensitive(self):
        self.seed_run("rep", "20261002-183000-AbC")
        self.assertEqual([r["runId"] for r in self.call("GET", "/api/runs/search?q=aBc")[1]],
                         ["20261002-183000-AbC"])

    def test_delete(self):
        st, out = self.call("DELETE", "/api/tasks/rep?purge-runs=1")
        self.assertEqual((st, out["deleted"], out["purgedRuns"]), (200, "rep", True))


class Cli(base.Case):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli.main(list(argv))
        return rc, out.getvalue(), err.getvalue()

    def test_add_list_remove(self):
        rc, out, _ = self.run_cli("add", "rep", "--schedule", "*/5 9-17 * * 1-5", "--command", "echo hi")
        self.assertEqual(rc, 0, out)
        rc, out, _ = self.run_cli("list")
        self.assertIn("every 5 minutes from 9:00 to 17:59 on weekdays", out)
        self.assertNotIn("GROUP", out)
        rc, out, err = self.run_cli("add", "rep", "--schedule", "0 9 * * *", "--command", "x")
        self.assertEqual(rc, 2)
        self.assertTrue(err.startswith("error: "))
        rc, out, err = self.run_cli("add", "x", "--schedule", "nope", "--command", "x")
        self.assertEqual(rc, 2)
        self.assertIn("5 cron fields", err)
        self.assertEqual(self.run_cli("remove", "rep", "--purge-runs")[0], 0)
        self.assertEqual(self.run_cli("runs", "rep")[0], 2)

    def test_help_shows_data_dir(self):
        rc, out, _ = self.run_cli("help")
        self.assertIn(str(identity.data_dir()), out)
        self.assertEqual(self.run_cli("bogus")[0], 2)

    def test_subcommand_help_prints_help_without_acting(self):
        rc, out, _ = self.run_cli("ui", "--help")
        self.assertEqual(rc, 0)
        self.assertIn(str(identity.data_dir()), out)


class Entry(base.Case):
    def test_entry_subprocess(self):
        r = subprocess.run([sys.executable, str(identity.ENTRY), "help"], capture_output=True, text=True,
                           timeout=30, cwd=str(self.tmp))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("usage: clockmaster", r.stdout)
        link = self.tmp / "bin" / "cm"
        os.symlink(identity.ENTRY, link)
        r = subprocess.run([str(link), "list"], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    import unittest
    unittest.main()
