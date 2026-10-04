"""Operations shared by the CLI and the web API — one implementation, one wording.

Every change to a task file is validated as a whole candidate BEFORE a byte
lands in tasks/, so a bad edit leaves the task exactly as it was.
"""
import os
import shutil
import subprocess
import sys
from datetime import datetime

import backends
import cost
import cron
import identity
import procs
import slots
import store
import taskdef
from errors import Conflict, NotFound, ValidationError

DRIFT_STATES = ("missing", "stale", "unloaded")


def backend():
    return backends.current()


# ---------- scheduler side ----------

def sync():
    """(ok, [lines]). A broken yaml aborts BEFORE the scheduler is touched — a typo
    must never unregister a task."""
    try:
        tasks = taskdef.load_all()
    except ValidationError as e:
        return False, [f"error: {e}", "nothing was changed in the scheduler"]
    try:
        lines = list(backend().sync(tasks))
    except (ValidationError, Conflict) as e:
        return False, [f"error: {e}"]
    for note in backend().notes():
        lines.append(f"note: {note}")
    return True, lines


def sync_text():
    ok, lines = sync()
    return ok, "\n".join(lines)


def orphans(tasks):
    """Registered with the scheduler, no yaml behind it."""
    have = {t.name for t in tasks}
    return [n for n in backend().registered_names() if n not in have]


# ---------- reading ----------

def next_run(task):
    """Aware datetime of the next scheduled start, None when disabled/never."""
    if not task.enabled:
        return None
    nxt = task.cron.next_after(datetime.now())
    return nxt.astimezone() if nxt else None


def run_json(meta):
    log = store.run_dir(meta["task"], meta["runId"]) / "output.log"
    usd, has_session = cost.run_cost(meta, log)
    return {**meta, "hasSession": has_session, "costUsd": usd}


def task_json(task, state, recent_n=20):
    recent = store.recent(task.name, recent_n)
    return {
        "name": task.name, "group": task.group, "description": task.description,
        "enabled": task.enabled, "notify": task.notify, "sound": task.sound,
        "schedule": task.schedule, "scheduleText": cron.describe(task.cron),
        "command": task.command, "workdir": str(task.workdir),
        "timeoutSec": task.timeout, "keep": task.keep,
        "parallel": task.parallel, "queue": task.queue, "catchup": task.catchup,
        "queued": slots.queued_count(store.queue_dir(task.name)),
        "state": state, "drift": state in DRIFT_STATES,
        "nextRun": store.iso(next_run(task)),
        "lastRun": run_json(recent[0]) if recent else None,
        "avgDurationSec": store.avg_duration(recent),
        # the task row's run strip: newest first, compact
        "lastRuns": [{"runId": m.get("runId"), "status": m.get("status", "?"), "start": m.get("start"),
                      "durationSec": m.get("durationSec"), "trigger": m.get("trigger"),
                      **({"queuedAt": m["queuedAt"]} if m.get("queuedAt") else {}),
                      **({"reason": m["reason"]} if m.get("reason") else {})} for m in recent],
    }


def spent(name):
    total = None
    for meta in store.recent(name):
        usd, _ = cost.run_cost(meta, store.run_dir(name, meta["runId"]) / "output.log")
        total = cost.add(total, usd)
    return total


# ---------- writing ----------

def _check_text(name, text):
    taskdef.from_text(name, text)  # raises ValidationError, task unchanged


def add(name, opts, force=False):
    taskdef.check_name(name)
    path = taskdef.path_of(name)
    if path.exists() and not force:
        raise Conflict(f"task '{name}' already exists ({path}) — pass --force to overwrite")
    text = taskdef.new_text(opts)
    _check_text(name, text)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def set_keys(name, edits):
    """Apply {key: value} to an existing task file; returns the reloaded Task."""
    path = taskdef.path_of(taskdef.load(name).name)
    text = taskdef.apply_edits(path.read_text(encoding="utf-8"), edits)
    _check_text(name, text)
    path.write_text(text, encoding="utf-8")
    return taskdef.load(name)


EDITABLE = ("schedule", "command", "workdir", "timeout", "keep", "description", "group", "parallel", "queue")


def edit(name, body):
    """Web edit form: changed keys of EDITABLE plus an optional rename.
    -> new name. A rename moves the yaml and the run history together."""
    if not isinstance(body, dict):
        raise ValidationError("body must be a json object")
    unknown = sorted(set(body) - set(EDITABLE) - {"name"})
    if unknown:
        raise ValidationError(f"not editable here: {', '.join(unknown)} — editable: name, {', '.join(EDITABLE)}")
    path = taskdef.load(name).path
    new = body.get("name", name)
    if not isinstance(new, str):
        raise ValidationError("name must be a string")
    new = new.strip()
    text = taskdef.apply_edits(path.read_text(encoding="utf-8"), {k: body[k] for k in EDITABLE if k in body})
    _check_text(new, text)
    if new == name:
        path.write_text(text, encoding="utf-8")
        return new
    target, runs, new_runs = taskdef.path_of(new), store.task_dir(name), store.task_dir(new)
    if target.exists():
        raise Conflict(f"a task named '{new}' already exists")
    if new_runs.exists():
        raise Conflict(f"run history for '{new}' is still on disk ({new_runs}) — move it away or pick another name")
    path.write_text(text, encoding="utf-8")
    path.rename(target)
    if runs.is_dir():
        runs.rename(new_runs)
    return new


def remove(name, purge_runs=False):
    """Delete the yaml, reconcile the scheduler, optionally drop the history.
    A registered task without a yaml (drift) is removable too. A run in flight
    keeps going — removing a schedule never kills work."""
    path = taskdef.path_of(name)
    if not path.is_file() and not backend().registered(name):
        raise NotFound(f"no such task '{name}'")
    if path.is_file():
        path.unlink()
    backend().unregister(name)
    ok, lines = sync()
    if purge_runs:
        store.purge(name)
    return ok, lines


# ---------- running ----------

def start_detached(name):
    """`run <name>` in the background; the run is on disk ~0.5 s later."""
    taskdef.load(name)
    subprocess.Popen([sys.executable, str(identity.ENTRY), "run", name, "--quiet"],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     cwd=str(identity.SKILL_DIR), **procs.DETACH_SERVER)


# ---------- resuming a claude session ----------

def _sq(s):
    return "'" + str(s).replace("'", "'\\''") + "'"


def _wq(s):
    return '"' + str(s).replace('"', '') + '"'


def resume_command(meta):
    if procs.IS_WIN:
        return f"cd /d {_wq(meta.get('workdir'))} && claude --resume {meta.get('sessionId')}"
    return f"cd {_sq(meta.get('workdir'))} && claude --resume {_sq(meta.get('sessionId'))}"


def can_open_terminal():
    if procs.IS_MAC:
        return True
    if procs.IS_WIN:
        return True
    import notify.desktop_linux as dl
    return bool(dl.display_env() and shutil.which("x-terminal-emulator"))


def _resumable(name, run_id):
    rdir = store.run_dir(name, run_id)
    meta = store.read(rdir) if rdir.is_dir() else None
    if not meta:
        raise NotFound(f"no run '{run_id}' for task '{name}'")
    if not meta.get("sessionId") or not meta.get("workdir"):
        raise Conflict("this run recorded no session id — nothing to resume")
    return meta, resume_command(meta)


def resume_info(name, run_id):
    """Read-only: {command, canOpen} — what a resume click would do."""
    meta, command = _resumable(name, run_id)
    has = bool(cost.session_file(meta.get("workdir"), meta.get("sessionId")))
    return {"command": command, "canOpen": has and can_open_terminal()}


def resume(name, run_id):
    """-> {opened, command, note}. The command is always returned, so a headless
    host can still copy it into its own terminal."""
    meta, command = _resumable(name, run_id)
    if not cost.session_file(meta.get("workdir"), meta.get("sessionId")):
        return {"opened": False, "command": command,
                "note": "no claude transcript for this run's session id — the command never started a session"}
    if not can_open_terminal():
        return {"opened": False, "command": command,
                "note": "no desktop session to open a terminal in — run the command yourself"}
    try:
        _open_terminal(meta, command)
    except (OSError, subprocess.SubprocessError, RuntimeError) as e:
        return {"opened": False, "command": command, "note": f"could not open a terminal: {e}"}
    return {"opened": True, "command": command, "note": "opened in a new terminal window"}


def _open_terminal(meta, command):
    if procs.IS_MAC:
        inner = f"/bin/zsh -lic {_sq(command)}".replace("\\", "\\\\").replace('"', '\\"')
        r = subprocess.run(["osascript",
                            "-e", f'tell application "iTerm" to create window with default profile command "{inner}"',
                            "-e", 'tell application "iTerm" to activate'],
                           capture_output=True, text=True, timeout=30)
    elif procs.IS_WIN:
        wt = shutil.which("wt.exe")
        sid = meta["sessionId"]
        if wt:
            argv = [wt, "-d", str(meta["workdir"]), "cmd.exe", "/k", "claude", "--resume", sid]
        else:
            argv = [os.environ.get("COMSPEC") or "cmd.exe", "/d", "/s", "/c",
                    f'start "{identity.APP}" /D {_wq(meta["workdir"])} cmd.exe /k claude --resume {sid}']
        r = subprocess.run(argv, capture_output=True, text=True, errors="replace", timeout=30)
    else:
        shell = procs.login_shell()
        subprocess.Popen(["x-terminal-emulator", "-e", shell, "-lic", command],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        return
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip() or "terminal launcher failed")
