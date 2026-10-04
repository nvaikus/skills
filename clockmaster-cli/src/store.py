"""Run history on disk: runs/<task>/<run-id>/{meta.json,output.log}.

run-id = YYYYmmdd-HHMMSS-<runner pid>, so names sort by start time.
meta.json keys (all optional across history — always .get()):
task runId trigger command workdir sessionId pid pgid start status exitCode
durationSec end queuedAt reason. Status: queued running success failed timeout
killed stopped skipped.

Queued run (slots.py holds its place in line): `start` = queuedAt until it
gets a slot, then `start` = the actual start. A run that never started
(skipped: queue full; stopped or killed while queued) has start = end =
the moment it was dropped and durationSec 0; queuedAt keeps the wait.

There is no daemon. A runner that dies (reboot, kill -9, logout) never writes
its outcome, so EVERY read reconciles: a `running` meta whose runner is
provably gone (or a `queued` one) becomes `killed` (exitCode null, end = output.log mtime). The
write inside a read is swallowed on failure and never notifies.
"""
import json
import shutil
from datetime import datetime

import identity
import procs
from errors import Conflict, NotFound

STATUSES = ("queued", "running", "success", "failed", "timeout", "killed", "stopped", "skipped")
FAILED = ("failed", "timeout", "killed", "skipped")
LIVE = ("queued", "running")


def task_dir(name):
    return identity.runs_dir() / name


def run_dir(name, run_id):
    return task_dir(name) / run_id


def queue_dir(name):
    """slots.py's lock files; a dot dir, so never a run."""
    return task_dir(name) / ".queue"


def run_dirs(name):
    """Newest first."""
    d = task_dir(name)
    if not d.is_dir():
        return []
    return sorted((p for p in d.iterdir() if p.is_dir() and not p.name.startswith(".")),
                  key=lambda p: p.name, reverse=True)


def read_raw(rdir):
    try:
        return json.loads((rdir / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write(rdir, meta):
    tmp = rdir / "meta.json.tmp"
    tmp.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    tmp.replace(rdir / "meta.json")


def read(rdir):
    """meta.json, reconciled, with `task` = the directory it is filed under (a
    rename moves history but never rewrites thousands of metas)."""
    meta = read_raw(rdir)
    if meta is None:
        return None
    if meta.get("status") in LIVE:
        meta = reconcile(rdir, meta)
    return {**meta, "task": rdir.parent.name, "runId": meta.get("runId") or rdir.name}


def recent(name, limit=None):
    dirs = run_dirs(name)
    if limit is not None:
        dirs = dirs[:limit]
    return [m for m in (read(d) for d in dirs) if m]


def avg_duration(metas):
    """Mean durationSec of the finished (success/failed) runs among metas, None without any."""
    ds = [m["durationSec"] for m in metas
          if m.get("status") in ("success", "failed") and isinstance(m.get("durationSec"), (int, float))]
    return round(sum(ds) / len(ds), 1) if ds else None


def stamp(text):
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        return None


def now():
    return datetime.now().astimezone()


def iso(dt):
    return dt.astimezone().isoformat(timespec="seconds") if dt else None


# ---------- liveness ----------

def runner_alive(meta):
    """True / False / None (= no pid recorded, cannot tell). The pid must still
    run OUR entry script with this run's task name — a recycled pid after a
    reboot belongs to someone else."""
    pid = meta.get("pid")
    if not isinstance(pid, int) or pid <= 0:
        return None
    if not procs.alive(pid):
        return False
    cmd = procs.cmdline(pid)
    if not cmd:
        return True  # alive but unreadable: never close what we cannot disprove
    name = meta.get("task") or ""
    return identity.ENTRY.name in cmd and bool(name) and name in cmd


def command_alive(meta):
    """Is the run's command group still there (orphaned by a dead runner)?
    Guarded by the command text, so a recycled pgid is never signalled."""
    pgid = meta.get("pgid")
    if not isinstance(pgid, int) or pgid <= 0:
        return False
    cmd = procs.cmdline(pgid)
    return bool(cmd and (meta.get("command") or "\0") in cmd)


def before_boot(meta):
    boot, start = procs.boot_time(), stamp(meta.get("start"))
    return bool(boot and start and start < boot)


def close(rdir, meta, status, end=None, recheck=True):
    """Record an outcome the runner never wrote. exitCode stays null — nobody
    reaped the child. `recheck`: a runner that finished meanwhile wins."""
    if recheck:
        fresh = read_raw(rdir)
        if fresh is not None and fresh.get("status") not in LIVE:
            return fresh
    if meta.get("status") == "queued":  # never started: a zero-length run
        end = end or stamp(meta.get("start")) or now()
        meta = {**meta, "status": status, "exitCode": None, "start": iso(end), "end": iso(end), "durationSec": 0}
        try:
            write(rdir, meta)
        except OSError:
            pass
        return meta
    start = stamp(meta.get("start"))
    if end is None:
        try:
            end = datetime.fromtimestamp((rdir / "output.log").stat().st_mtime).astimezone()
        except OSError:
            end = None
    if end is None or (start and end < start):
        end = start or now()
    meta = {**meta, "status": status, "exitCode": None, "end": iso(end),
            "durationSec": round((end - start).total_seconds(), 1) if start else None}
    try:
        write(rdir, meta)
    except OSError:
        pass  # a read may not fail because the history is read-only
    return meta


def reconcile(rdir, meta):
    meta = {**meta, "task": meta.get("task") or rdir.parent.name}
    alive = runner_alive(meta)
    if alive:
        return meta
    if alive is False or before_boot(meta):
        return close(rdir, meta, "killed")
    return meta


def fmt_dur(s):
    s = s or 0
    if s < 60:
        return f"{s:.1f}s"
    m, sec = divmod(int(s), 60)
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m {sec:02d}s"


def stop(rdir):
    """End a live run on purpose -> (meta, note). The runner is signalled FIRST
    (it is the only writer of this meta and would overwrite `stopped` with the
    child's failure), then the command's own group."""
    meta = read_raw(rdir)
    if meta is None:
        raise Conflict(f"run '{rdir.name}' has no readable meta.json")
    meta = {**meta, "task": meta.get("task") or rdir.parent.name}
    pgid = meta.get("pgid")
    if meta.get("status") == "queued":
        return _stop_queued(rdir, meta)
    if meta.get("status") != "running":
        if command_alive(meta):
            procs.kill_group(pgid)
            return meta, (f"already {meta.get('status')}, but its command was still running"
                          f" — killed the orphaned process group {pgid}")
        return meta, f"already {meta.get('status')} — nothing to stop"
    alive, pid = runner_alive(meta), meta.get("pid")
    if alive is False or (alive is None and before_boot(meta)):
        orphan = command_alive(meta)
        if orphan:
            procs.kill_group(pgid)
        meta = close(rdir, meta, "killed", end=now() if orphan else None)
        return meta, ("its runner was already gone"
                      + (f", killed the orphaned process group {pgid}" if orphan else "")
                      + f" — recorded as killed, ended {meta.get('end')}")
    if not isinstance(pid, int) or pid <= 0:
        return close(rdir, meta, "killed"), "no runner pid recorded (older run) — nothing to signal, recorded as killed"
    procs.kill_one(pid)
    if isinstance(pgid, int) and pgid > 0:
        procs.kill_group(pgid)
    meta = close(rdir, meta, "stopped", end=now(), recheck=False)
    what = f"runner {pid}" + (f" and process group {pgid}" if pgid else "")
    return meta, f"stopped after {fmt_dur(meta.get('durationSec'))} ({what} killed)"


def _stop_queued(rdir, meta):
    """Take a waiting run out of the line: its runner dies, the OS drops its
    lock (= its place in line). If it got a slot meanwhile, its command dies too."""
    pid = meta.get("pid")
    if runner_alive(meta) and isinstance(pid, int) and pid > 0:
        procs.kill_one(pid)
    fresh = read_raw(rdir) or meta
    pgid = fresh.get("pgid")
    if fresh.get("status") == "running" and isinstance(pgid, int) and pgid > 0:
        procs.kill_group(pgid)
        meta = close(rdir, {**fresh, "task": meta["task"]}, "stopped", end=now(), recheck=False)
        return meta, f"it had just started — stopped (runner {pid} and process group {pgid} killed)"
    if fresh.get("status") not in LIVE:
        return fresh, f"already {fresh.get('status')} — nothing to stop"
    meta = close(rdir, meta, "stopped", end=now(), recheck=False)
    return meta, f"removed from the queue (runner {pid} ended)"


def pick_to_stop(name, run_id=None):
    """The run `stop` acts on: the given one, else the newest that CLAIMS to be
    running (raw read — reconciling first would hide it), else the newest whose
    command outlived its runner."""
    dirs = run_dirs(name)
    if not dirs:
        raise NotFound(f"no runs yet for '{name}'")
    if run_id:
        rdir = run_dir(name, run_id)
        if not rdir.is_dir():
            raise NotFound(f"no run '{run_id}' for task '{name}'")
        return rdir
    metas = [(d, read_raw(d) or {}) for d in dirs]
    for status in LIVE[::-1]:  # running first, then the newest queued
        for d, m in metas:
            if m.get("status") == status:
                return d
    for d, m in metas:
        if command_alive(m):
            return d
    raise NotFound(f"nothing of '{name}' is still running or queued — nothing to stop")


def prune(name, keep):
    if keep is None:
        return
    for old in run_dirs(name)[keep:]:
        shutil.rmtree(old, ignore_errors=True)


def purge(name):
    shutil.rmtree(task_dir(name), ignore_errors=True)
