"""One run of one task: take a slot (or wait in line), record, spawn, echo,
enforce the timeout, finish, notify.

Exit code of the runner: 0 success, 124 timeout, 1 anything else (a skipped
run too). A missing workdir is a failed run with exitCode 78 (EX_CONFIG) and a
one-line log.

Limit: `parallel` runs of a task at once (slots.py, cross-process). A run that
arrives while they are taken waits as `queued` (FIFO, up to `queue` runs), then
starts for real: `start` and the timeout count from then. Queue full = the run
is recorded as `skipped` and never executed.
"""
import os
import subprocess
import sys
import time
import traceback
import uuid
from datetime import datetime

import identity
import procs
import slots
import store
import taskdef

MARKS = {"success": "✓", "failed": "✗", "timeout": "✗ timeout", "stopped": "■ stopped", "killed": "✗ killed",
         "skipped": "✗ skipped"}


def _echo(log_path, pos):
    try:
        with open(log_path, "rb") as f:
            f.seek(pos)
            chunk = f.read()
    except OSError:
        return pos
    if chunk:
        try:
            sys.stdout.buffer.write(chunk)
            sys.stdout.buffer.flush()
        except (AttributeError, OSError, ValueError):
            pass
    return pos + len(chunk)


def _spawn(task, log, session_id):
    argv, extra, quiet = procs.shell_spawn(task.command, log.fileno())
    env = {**os.environ, "TERM": "dumb", identity.ENV_SESSION: session_id}
    return subprocess.Popen(
        argv, cwd=str(task.workdir), stdin=subprocess.DEVNULL, stdout=log,
        stderr=subprocess.DEVNULL if quiet else subprocess.STDOUT,
        env=env, **procs.DETACH, **extra)


def exec_task(name, trigger="manual", echo=False):
    """Run `name` now. Returns the runner exit code (does not sys.exit)."""
    task = taskdef.load(name)
    if trigger == "schedule":
        import backends
        if not backends.current().exec_guard(task, datetime.now()):
            return 0  # the OS scheduler over-fired (Windows day AND weekday): not a run
        if not task.catchup and not taskdef.on_time(task, datetime.now()):
            return 0  # a missed start fired late (wake/boot catch-up) and the task opted out
    run_id = time.strftime("%Y%m%d-%H%M%S") + f"-{os.getpid()}"
    rdir = store.run_dir(name, run_id)
    rdir.mkdir(parents=True, exist_ok=True)
    log_path = rdir / "output.log"
    gate = slots.Gate(store.queue_dir(name))
    try:
        return _exec(task, trigger, echo, run_id, rdir, log_path, gate)
    finally:
        gate.release()


def _parallel_now(task):
    """`parallel` as the yaml says it now (an edit reaches runs already waiting)."""
    def get():
        try:
            fresh = taskdef.find(task.name)
        except Exception:
            fresh = None
        return fresh.parallel if fresh else task.parallel
    return get


def _skip(task, meta, rdir, log_path, waiting, echo):
    reason = f"queue full ({waiting} waiting)" if task.queue else "queue full (queue: 0)"
    meta.update(status="skipped", reason=reason, end=meta["start"], durationSec=0)
    log_path.write_text(f"skipped, not run: {reason}; the task runs {taskdef.parallel_text(task.parallel)}\n",
                        encoding="utf-8")
    store.write(rdir, meta)
    store.prune(task.name, task.keep)
    if echo:
        print(f"{MARKS['skipped']} skipped: {reason}")
    try:
        import notify
        notify.dispatch(task, meta, log_path)
    except Exception:
        pass
    return 1


def _exec(task, trigger, echo, run_id, rdir, log_path, gate):
    name = task.name
    meta = {
        "task": name, "runId": run_id, "trigger": trigger,
        "command": task.command, "workdir": str(task.workdir),
        # exported to the command; a claude run that adopts it as --session-id
        # gets cost + resume in the UI
        "sessionId": str(uuid.uuid4()),
        # the liveness witnesses reconcile needs (store.py)
        "pid": os.getpid(), "pgid": None,
        "start": store.iso(store.now()), "status": "running",
        "exitCode": None, "durationSec": None,
    }
    verdict = gate.enter(task.parallel, task.queue)
    if isinstance(verdict, tuple):
        return _skip(task, meta, rdir, log_path, verdict[1], echo)
    if verdict == "queued":
        meta.update(status="queued", queuedAt=meta["start"])
        log_path.touch()  # the UI tails an empty log, not a 404
        store.write(rdir, meta)
        if echo:
            print(f"queued: {taskdef.parallel_text(task.parallel)} and that is taken — "
                  f"waiting, place {gate.position()} in line (Ctrl-C leaves the queue)", flush=True)
        try:
            gate.wait_turn(_parallel_now(task))
        except KeyboardInterrupt:
            store.close(rdir, meta, "stopped", end=store.now(), recheck=False)
            raise
        meta.update(status="running", start=store.iso(store.now()))
    store.write(rdir, meta)

    t0, status, rc = time.monotonic(), None, None
    if not task.workdir.is_dir():
        log_path.write_text(f"workdir does not exist: {task.workdir}\n", encoding="utf-8")
        status, rc = "failed", 78
    else:
        with open(log_path, "ab") as log:
            proc = _spawn(task, log, meta["sessionId"])
            meta["pgid"] = proc.pid  # detached: the child leads its own group
            store.write(rdir, meta)
            deadline = t0 + task.timeout if task.timeout else None
            pos = 0
            while True:
                rc = proc.poll()
                if echo:
                    pos = _echo(log_path, pos)
                if rc is not None:
                    break
                if deadline and time.monotonic() > deadline:
                    status = "timeout"
                    procs.kill_group(proc.pid, proc.wait)
                    rc = proc.wait()
                    break
                time.sleep(0.3)
            if echo:
                _echo(log_path, pos)

    duration = time.monotonic() - t0
    status = status or ("success" if rc == 0 else "failed")
    meta.update(status=status, exitCode=rc, durationSec=round(duration, 1), end=store.iso(store.now()))
    store.write(rdir, meta)
    store.prune(name, task.keep)
    if echo:
        print(f"\n{MARKS.get(status, status)} {status} (exit {rc}) in {store.fmt_dur(duration)} — {log_path}")
    try:  # after the terminal answer; a notification may never cost a run
        import notify
        notify.dispatch(task, meta, log_path)
    except Exception:
        pass
    return 0 if status == "success" else (124 if status == "timeout" else 1)


def io_log(name):
    d = identity.data_dir() / "scheduler-io"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{name}.log"


def exec_scheduled(name):
    """`_exec` entry. Under pythonw (Windows) stdout/stderr are None, so the CLI's
    own output and crashes go to scheduler-io/<name>.log — the analog of
    launchd's StandardErrorPath. Non-empty io log = the tool failed, not the task."""
    if sys.stdout is not None and sys.stderr is not None:
        return exec_task(name, "schedule")
    out, err = sys.stdout, sys.stderr
    with io_log(name).open("a", encoding="utf-8", errors="replace") as fh:
        sys.stdout = sys.stderr = fh
        try:
            return exec_task(name, "schedule")
        except SystemExit:
            raise
        except BaseException:
            fh.write(f"\n=== {datetime.now().isoformat(timespec='seconds')} _exec crashed ===\n")
            traceback.print_exc(file=fh)
            raise
        finally:
            sys.stdout, sys.stderr = out, err
