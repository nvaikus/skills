"""JSON handlers for the web UI. Contract: src/CLAUDE.md (camelCase, fixed).

Handlers take (req, **url params) and return Resp. Core failures arrive as
errors.UserError subclasses and become {error} with their status in server.py.
"""
import json
import time
from datetime import timedelta

import backends
import cron
import identity
import notify
import ops
import store
import taskdef
from errors import NotFound, ValidationError

DEFAULT_RUNS = 50
SEARCH_LIMIT = 20
TIMELINE_MAX_DAYS = 92
TIMELINE_MAX_PLANNED = 1000
CLICK_TTL = 120


class Resp:
    def __init__(self, body, status=200, ctype="application/json; charset=utf-8"):
        self.body, self.status, self.ctype = body, status, ctype


def ok(obj, status=200):
    return Resp(json.dumps(obj).encode(), status)


def text(data, ctype="text/plain; charset=utf-8"):
    return Resp(data if isinstance(data, bytes) else data.encode(), 200, ctype)


def fail(status, msg):
    return ok({"error": msg}, status)


def q_int(req, key, default):
    try:
        return int((req.query.get(key) or [default])[0])
    except (TypeError, ValueError):
        raise ValidationError(f"{key} must be a whole number")


def body_json(req):
    try:
        data = json.loads(req.body or b"{}")
    except ValueError:
        raise ValidationError("body must be json")
    if not isinstance(data, dict):
        raise ValidationError("body must be a json object")
    return data


def _states(tasks):
    return backends.states(ops.backend(), tasks)


# ---------- reads ----------

def h_app(req):
    be = ops.backend()
    return ok({"app": identity.TITLE, "platform": identity.platform(), "backend": be.name,
               "dataDir": str(identity.data_dir()), "notes": be.notes(),
               "sounds": list(taskdef.SOUNDS), "canOpenTerminal": ops.can_open_terminal(),
               "notifyChannels": notify.channels()})


def h_drift(req):
    """Header's "N out of sync": tasks the scheduler disagrees with + scheduler entries with no task."""
    tasks = taskdef.load_all()
    states = _states(tasks)
    return ok({"drift": sum(1 for s in states.values() if s in ops.DRIFT_STATES) + len(ops.orphans(tasks))})


def h_tasks(req):
    tasks = taskdef.load_all()
    states = _states(tasks)
    return ok([ops.task_json(t, states[t.name]) for t in tasks])


def h_task(req, name):
    t = taskdef.load(name)
    out = ops.task_json(t, ops.backend().state(t))
    out["yaml"] = t.path.read_text(encoding="utf-8")
    out["spentUsd"] = ops.spent(name)
    return ok(out)


def h_schedule(req):
    """Live preview under the cron field: plain words + next runs, from the one cron parser."""
    expr = " ".join(((req.query.get("cron") or [""])[0]).split())
    c = cron.parse(expr)
    return ok({"cron": expr, "text": cron.describe(c),
               "next": [store.iso(at) for at in cron.upcoming(c, 3)]})


def h_runs(req, name):
    taskdef.load(name)
    n = max(q_int(req, "n", DEFAULT_RUNS), 1)
    return ok([ops.run_json(m) for m in store.recent(name, n)])


def h_run_search(req):
    """Search box: runs of existing tasks whose run id contains q (case-insensitive),
    newest first. Matches directory names only; reads meta.json of the hits alone."""
    q = ((req.query.get("q") or [""])[0]).strip().lower()
    limit = min(max(q_int(req, "limit", SEARCH_LIMIT), 1), 200)
    if not q:
        return ok([])
    tasks_dir = identity.tasks_dir()
    names = sorted(p.stem for p in tasks_dir.glob("*.yaml") if not p.name.startswith("_")) \
        if tasks_dir.is_dir() else []
    hits = []
    for name in names:
        d = store.task_dir(name)
        if not d.is_dir():
            continue
        hits += [(p.name, name) for p in d.iterdir() if q in p.name.lower() and p.is_dir()]
    out = []
    for run_id, name in sorted(hits, reverse=True):
        meta = store.read(store.run_dir(name, run_id))
        if meta is None:
            continue
        out.append({"task": name, "runId": meta["runId"], "status": meta.get("status", "?"),
                    "start": meta.get("start"), "durationSec": meta.get("durationSec")})
        if len(out) >= limit:
            break
    return ok(out)


def h_log(req, name, run_id):
    log = store.run_dir(name, run_id) / "output.log"
    if not log.is_file():
        raise NotFound("no output.log for this run")
    return text(log.read_bytes())


def _lane_runs(name, frm, to, now):
    out = []
    for meta in store.recent(name):
        start = store.stamp(meta.get("start"))
        if not start:
            continue
        end = store.stamp(meta.get("end"))
        if (end or now) < frm:
            continue  # no break: with queueing/skips an older run can end later
        if start > to:
            continue
        out.append({"runId": meta["runId"], "start": store.iso(start), "end": store.iso(end),
                    "durationSec": meta.get("durationSec"), "status": meta.get("status", "?"),
                    "trigger": meta.get("trigger", "?"), "exitCode": meta.get("exitCode"),
                    **({"queuedAt": meta["queuedAt"]} if meta.get("queuedAt") else {}),
                    **({"reason": meta["reason"]} if meta.get("reason") else {})})
    return out


def _planned(task, frm, to):
    """Future starts in [frm, to], walked in naive local time (DST-safe), each
    re-stamped with the offset its own date has. Over TIMELINE_MAX_PLANNED: every
    k-th start across the whole window (not the first N), k returned as `every`."""
    starts = list(task.cron.walk(frm.astimezone().replace(tzinfo=None), to.astimezone().replace(tzinfo=None)))
    every = -(-len(starts) // TIMELINE_MAX_PLANNED) if len(starts) > TIMELINE_MAX_PLANNED else 1
    return [store.iso(dt.astimezone()) for dt in starts[::every]], every


def h_timeline(req):
    frm = store.stamp((req.query.get("from") or [""])[0])
    to = store.stamp((req.query.get("to") or [""])[0])
    if not frm or not to:
        raise ValidationError("from and to must be ISO timestamps")
    if frm.tzinfo is None:
        frm = frm.astimezone()
    if to.tzinfo is None:
        to = to.astimezone()
    if to <= frm:
        raise ValidationError("to must be later than from")
    to = min(to, frm + timedelta(days=TIMELINE_MAX_DAYS))
    now = store.now()
    lanes = []
    for t in taskdef.load_all():
        planned, every = _planned(t, max(frm, now), to) if t.enabled and to > now else ([], 1)
        lanes.append({"task": t.name, "group": t.group, "enabled": t.enabled,
                      "runs": _lane_runs(t.name, frm, to, now),
                      "planned": planned, "plannedTruncated": every > 1, "plannedEvery": every,
                      "avgDurationSec": store.avg_duration(store.recent(t.name, 20))})
    return ok(lanes)


def h_notify_click(req):
    """Which run a just-clicked macOS banner was about — handed out once."""
    path = identity.data_dir() / "notify-click.json"
    try:
        clicked = path.stat().st_mtime
        crumb = json.loads(path.read_text(encoding="utf-8"))
        path.unlink()
    except (OSError, ValueError):
        return ok({})
    if time.time() - clicked > CLICK_TTL:
        return ok({})
    name = crumb.get("task") if isinstance(crumb, dict) else None
    if not name or taskdef.find(name) is None:
        return ok({})
    return ok({"task": name, "runId": crumb.get("runId")})


# ---------- writes ----------

def h_edit(req, name):
    new = ops.edit(name, body_json(req))
    good, out = ops.sync_text()
    return ok({"ok": good, "name": new, "syncOutput": out})


def h_delete(req, name):
    purge = (req.query.get("purge-runs") or [""])[0] in ("1", "true", "yes")
    good, lines = ops.remove(name, purge)
    return ok({"ok": good, "deleted": name, "purgedRuns": purge, "syncOutput": "\n".join(lines)})


def h_run(req, name):
    ops.start_detached(name)
    return ok({"started": name}, 202)


def h_enabled(req, name):
    want = body_json(req).get("enabled")
    if not isinstance(want, bool):
        raise ValidationError("enabled must be true or false")
    t = ops.set_keys(name, {"enabled": "true" if want else "false"})
    good, out = ops.sync_text()
    return ok({"ok": good, "enabled": t.enabled, "syncOutput": out})


def h_notify(req, name):
    want = body_json(req).get("notify")
    if want not in taskdef.NOTIFY_VALUES:
        raise ValidationError(f"notify must be one of {', '.join(taskdef.NOTIFY_VALUES)}")
    return ok({"ok": True, "notify": ops.set_keys(name, {"notify": want}).notify})


def h_sound(req, name):
    want = body_json(req).get("sound")
    if want not in taskdef.SOUND_VALUES:
        raise ValidationError(f"sound must be one of {', '.join(taskdef.SOUND_VALUES)}")
    return ok({"ok": True, "sound": ops.set_keys(name, {"sound": want}).sound})


def h_stop(req, name, run_id):
    rdir = store.run_dir(name, run_id)
    if not rdir.is_dir():
        raise NotFound(f"no run '{run_id}' for task '{name}'")
    meta, note = store.stop(rdir)
    meta = {**meta, "task": name, "runId": meta.get("runId") or run_id}
    return ok({"run": ops.run_json(meta), "note": note})


def h_resume(req, name, run_id):
    return ok(ops.resume(name, run_id))


def h_resume_info(req, name, run_id):
    return ok(ops.resume_info(name, run_id))


def h_sync(req):
    good, out = ops.sync_text()
    return ok({"ok": good, "output": out})


NAME = r"(?P<name>[a-z0-9][a-z0-9-]*)"
RID = r"(?P<run_id>[0-9-]+)"
ROUTES = [
    ("GET", r"/api/app$", h_app),
    ("GET", r"/api/drift$", h_drift),
    ("GET", r"/api/tasks$", h_tasks),
    ("GET", rf"/api/tasks/{NAME}$", h_task),
    ("GET", rf"/api/tasks/{NAME}/runs$", h_runs),
    ("GET", rf"/api/tasks/{NAME}/runs/{RID}/log$", h_log),
    ("GET", rf"/api/tasks/{NAME}/runs/{RID}/resume$", h_resume_info),
    ("GET", r"/api/runs/search$", h_run_search),
    ("GET", r"/api/timeline$", h_timeline),
    ("GET", r"/api/notify-click$", h_notify_click),
    ("GET", r"/api/schedule$", h_schedule),
    ("POST", rf"/api/tasks/{NAME}$", h_edit),
    ("DELETE", rf"/api/tasks/{NAME}$", h_delete),
    ("POST", rf"/api/tasks/{NAME}/run$", h_run),
    ("POST", rf"/api/tasks/{NAME}/enabled$", h_enabled),
    ("POST", rf"/api/tasks/{NAME}/notify$", h_notify),
    ("POST", rf"/api/tasks/{NAME}/sound$", h_sound),
    ("POST", rf"/api/tasks/{NAME}/runs/{RID}/stop$", h_stop),
    ("POST", rf"/api/tasks/{NAME}/runs/{RID}/resume$", h_resume),
    ("POST", r"/api/sync$", h_sync),
]
