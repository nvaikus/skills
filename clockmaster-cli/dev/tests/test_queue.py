"""parallel / queue: slots, FIFO across processes, cap -> skipped, dead holders,
timeout from the actual start, stopping a queued run."""
import json
import os
import signal
import subprocess
import sys
import threading
import time
from unittest import mock

import base
import ops
import runner
import slots
import store
import taskdef
from errors import ValidationError

T = 'schedule: "0 9 * * *"\n'


def wait_for(cond, secs=10, step=0.02):
    deadline = time.monotonic() + secs
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(step)
    return False


def hold(name):
    """A slot held by this test process (as if a run were going)."""
    g = slots.Gate(store.queue_dir(name))
    assert g.enter(1, 20) == "run"
    return g


class Defs(base.Case):
    def test_defaults_and_validation(self):
        self.write_task("d", T + "command: true\n")
        t = taskdef.load("d")
        self.assertEqual((t.parallel, t.queue), (1, 20))
        self.write_task("e", T + "command: true\nparallel: 3\nqueue: 0\n")
        t = taskdef.load("e")
        self.assertEqual((t.parallel, t.queue), (3, 0))
        self.assertEqual(taskdef.parallel_text(1), "1 at a time")
        self.assertEqual(taskdef.parallel_text(3), "up to 3 at a time")
        for bad in ("parallel: 0", "parallel: x", "queue: -1"):
            with self.assertRaises(ValidationError):
                taskdef.from_text("f", T + "command: true\n" + bad + "\n")

    def test_web_edit_and_task_json(self):
        self.write_task("w", T + "command: true\n")
        ops.edit("w", {"parallel": "2", "queue": "5"})
        t = taskdef.load("w")
        j = ops.task_json(t, "ok")
        self.assertEqual((j["parallel"], j["queue"], j["queued"]), (2, 5, 0))


class Slots(base.Case):
    def test_acquire_up_to_parallel_then_queue(self):
        q = store.queue_dir("s")
        a, b, c = slots.Gate(q), slots.Gate(q), slots.Gate(q)
        self.assertEqual(a.enter(2, 20), "run")
        self.assertEqual(b.enter(2, 20), "run")
        self.assertEqual(c.enter(2, 20), "queued")
        self.assertEqual(slots.queued_count(q), 1)
        self.assertFalse(c.advance(2))
        a.release()
        self.assertTrue(c.advance(2))
        self.assertEqual(slots.queued_count(q), 0)
        for g in (b, c):
            g.release()

    def test_cap(self):
        q = store.queue_dir("s")
        gates = [slots.Gate(q) for _ in range(3)]
        self.assertEqual(gates[0].enter(1, 1), "run")
        self.assertEqual(gates[1].enter(1, 1), "queued")
        self.assertEqual(gates[2].enter(1, 1), ("full", 1))
        for g in gates:
            g.release()

    def test_dead_holder_frees_its_slot_and_place(self):
        q = store.queue_dir("s")
        src = ("import sys, time; sys.path.insert(0, sys.argv[1]); import slots, pathlib;"
               "g = slots.Gate(pathlib.Path(sys.argv[2])); g.enter(1, 20); g2 = slots.Gate(pathlib.Path(sys.argv[2]));"
               "print(g2.enter(1, 20), flush=True); time.sleep(60)")
        p = subprocess.Popen([sys.executable, "-c", src, str(base.SKILL / "src"), str(q)], stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(p.stdout.readline().strip(), "queued")
            g = slots.Gate(q)
            self.assertEqual(g.enter(1, 20), "queued")  # slot taken and one ahead in line
            self.assertEqual(slots.queued_count(q), 2)
            os.kill(p.pid, signal.SIGKILL)
            p.wait(5)
            self.assertTrue(g.advance(1))  # no cleanup ran: the OS dropped both locks
            g.release()
        finally:
            if p.poll() is None:
                p.kill()
            p.stdout.close()


class Queue(base.Case):
    def spawn(self, name):
        return subprocess.Popen([sys.executable, str(base.identity.ENTRY), "run", name, "--quiet"],
                                env=dict(os.environ), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def statuses(self, name):
        return [m["status"] for m in reversed(store.recent(name))]  # oldest first

    def test_fifo_across_processes_and_cap(self):
        out = self.tmp / "order.txt"
        self.write_task("f", T + f'command: echo "$TASK_SESSION_ID" >> "{out}"\nqueue: 3\n')
        g = hold("f")
        procs = []
        try:
            for i in range(4):
                procs.append(self.spawn("f"))
                want = min(i + 1, 3)
                self.assertTrue(wait_for(lambda: slots.queued_count(store.queue_dir("f")) == want
                                         and len(store.run_dirs("f")) == i + 1), f"runner {i} not recorded")
            self.assertTrue(wait_for(lambda: procs[3].poll() is not None))
            self.assertEqual(procs[3].returncode, 1)
            self.assertEqual(self.statuses("f"), ["queued", "queued", "queued", "skipped"])
            skipped = store.recent("f", 1)[0]
            self.assertIn("queue full", skipped["reason"])
            self.assertEqual(skipped["durationSec"], 0)
            g.release()
            for p in procs:
                p.wait(10)
        finally:
            g.release()
            for p in procs:
                if p.poll() is None:
                    p.kill()
        runs = list(reversed(store.recent("f")))  # arrival order
        self.assertEqual([m["status"] for m in runs], ["success"] * 3 + ["skipped"])
        sids = out.read_text().split()
        self.assertEqual(sids, [m["sessionId"] for m in runs[:3]])  # FIFO
        for m in runs[:3]:
            self.assertLessEqual(m["queuedAt"], m["start"])

    def test_timeout_counts_from_actual_start(self):
        self.write_task("t", T + "command: sleep 5\n")
        real = taskdef.load

        def short(name):  # yaml timeouts are whole seconds; keep the test fast
            t = real(name)
            t.timeout = 0.4
            return t
        g = hold("t")
        threading.Timer(0.6, g.release).start()  # queued longer than the timeout
        with mock.patch.object(taskdef, "load", short):
            self.assertEqual(runner.exec_task("t"), 124)
        m = store.recent("t", 1)[0]
        self.assertEqual(m["status"], "timeout")
        self.assertGreaterEqual(m["durationSec"], 0.3)  # ran ~0.4 s, not killed at once
        self.assertGreaterEqual(store.stamp(m["start"]), store.stamp(m["queuedAt"]))  # stamps are whole seconds

    def test_stop_queued_run(self):
        marker = self.tmp / "ran"
        self.write_task("q", T + f'command: touch "{marker}"\n')
        g = hold("q")
        p = self.spawn("q")
        try:
            self.assertTrue(wait_for(lambda: store.run_dirs("q") and
                                     (store.read_raw(store.run_dirs("q")[0]) or {}).get("status") == "queued"))
            rdir = store.pick_to_stop("q")
            meta, note = store.stop(rdir)
            self.assertEqual(meta["status"], "stopped", note)
            self.assertEqual(meta["durationSec"], 0)
            p.wait(10)
            self.assertEqual(slots.queued_count(store.queue_dir("q")), 0)
            g.release()
            time.sleep(0.3)
            self.assertFalse(marker.exists())
            self.assertEqual(store.read(rdir)["status"], "stopped")
        finally:
            g.release()
            if p.poll() is None:
                p.kill()

    def test_dead_queued_runner_reconciles_to_killed(self):
        rdir = store.run_dir("k", "20250101-000000-1")
        rdir.mkdir(parents=True)
        dead = subprocess.Popen(["true"])
        dead.wait()
        store.write(rdir, {"task": "k", "runId": rdir.name, "pid": dead.pid, "status": "queued",
                           "start": "2025-01-01T00:00:00+00:00", "queuedAt": "2025-01-01T00:00:00+00:00"})
        m = store.read(rdir)
        self.assertEqual((m["status"], m["durationSec"]), ("killed", 0))
        self.assertEqual(json.loads((rdir / "meta.json").read_text())["status"], "killed")

    def test_queue_dir_is_not_a_run(self):
        self.write_task("r", T + "command: true\n")
        runner.exec_task("r")
        self.assertTrue(store.queue_dir("r").is_dir())
        self.assertEqual(len(store.run_dirs("r")), 1)


if __name__ == "__main__":
    import unittest
    unittest.main()
