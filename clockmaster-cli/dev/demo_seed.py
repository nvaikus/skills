#!/usr/bin/env python3
"""Fill a scratch data dir with demo tasks and a week of run history, for UI work
and screenshots. Never touches an OS scheduler (uses the null backend).

    python3 dev/demo_seed.py [DIR]            # default: a fresh temp dir
    HOME=DIR/home CLOCKMASTER_HOME=DIR CLOCKMASTER_SCHEDULER=null python3 clockmaster.py ui --fg

Seeds: two groups + standalone tasks; success, failed, timeout, stopped and
killed runs over the last 7 days; one run that stays `running` (a detached
sleeper that looks like a runner, ~2 h); a claude run whose log carries a
TASK_COST_USD line and inbox-triage runs with a claude transcript under DIR/home
(hasSession + cost); no run ends after now; one disabled task; one task left unregistered (drift); render-thumbs
(parallel 2) with real runners started through the CLI: 2 running + 2 queued
(they sleep 30 min; kill them with `pkill -f 'run render-thumbs'`), plus past
runs that waited in the queue and one skipped (queue full).
Refuses a dir that already holds tasks unless --force.
"""
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL / "src"))

TASKS = {
    "daily-report": dict(schedule="0 9 * * 1-5", command="python3 report.py --daily",
                         description="Weekday morning digest", group="reports", notify="on"),
    "weekly-summary": dict(schedule="30 18 * * 5", command="python3 report.py --weekly",
                           description="Friday wrap-up", group="reports", timeout="30m"),
    "backup-db": dict(schedule="0 3 * * *", command="pg_dump app > /tmp/app.sql",
                      description="Nightly database dump", group="maintenance", keep="20"),
    "cleanup-tmp": dict(schedule="15 */6 * * *", command="find /tmp -mtime +7 -delete",
                        group="maintenance", notify="off"),
    "inbox-triage": dict(schedule="*/30 8-19 * * 1-5",
                         command='claude -p --session-id "$TASK_SESSION_ID" "triage my inbox"',
                         description="Claude sorts new mail", sound="Glass"),
    "sync-notes": dict(schedule="*/15 * * * *", command="rsync -a ~/notes/ backup:/notes/"),
    "render-thumbs": dict(schedule="0 * * * *", command="sleep 1800", parallel="2", queue="5",
                          description="Bursty: many uploads at once", group="media"),
    "monthly-invoice": dict(schedule="30 3 1 * *", command="./invoice.sh",
                            description="First of the month", disabled=True),
}
NOT_REGISTERED = "sync-notes"  # yaml exists, scheduler does not know it -> drift
LOGS = {
    "success": ["starting", "fetched 42 items", "wrote report.html", "done"],
    "failed": ["starting", "Traceback (most recent call last):",
               '  File "report.py", line 12, in <module>', "ConnectionError: host unreachable"],
    "timeout": ["starting", "waiting for lock ..."],
    "stopped": ["starting", "processing batch 1/9"],
    "killed": ["starting", "processing batch 3/9"],
    "skipped": ["skipped, not run: queue full (5 waiting); the task runs up to 2 at a time"],
}


WORKDIR = None  # set in main: <data>/home, the seeded HOME


def transcript(sid, usd_turns):
    """A minimal claude transcript for session `sid` (one priced assistant turn
    per entry) under the seeded HOME, so the run gets hasSession + a cost."""
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(WORKDIR))
    path = WORKDIR / ".claude" / "projects" / slug / f"{sid}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"type": "user", "sessionId": sid, "message": {"role": "user", "content": "triage my inbox"}})]
    for i, out_tokens in enumerate(usd_turns):
        lines.append(json.dumps({"type": "assistant", "sessionId": sid, "requestId": f"req_demo_{i}",
                                 "message": {"model": "claude-opus-5", "role": "assistant",
                                             "usage": {"input_tokens": 1200, "output_tokens": out_tokens,
                                                       "cache_read_input_tokens": 18000}}}))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_run(runs, name, task, start, status, trigger="schedule", cost=None, pid=None, session=False, extra=None):
    run_id = start.strftime("%Y%m%d-%H%M%S") + f"-{pid or random.randint(2000, 60000)}"
    rdir = runs / name / run_id
    rdir.mkdir(parents=True, exist_ok=True)
    lines = list(LOGS.get(status, ["starting"]))
    if cost is not None:
        lines.append(f"TASK_COST_USD={cost}")
    (rdir / "output.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
    dur = {"success": 12.4, "failed": 3.1, "timeout": 1800.0, "stopped": 95.0, "killed": 41.0, "skipped": 0.0}.get(status)
    if dur is not None:  # nothing seeded may end in the future
        dur = max(0.5, min(dur, (datetime.now().astimezone() - start).total_seconds() - 1))
        dur = round(dur, 1)
    sid = f"demo-{run_id}"
    if session:
        transcript(sid, [800, 2400, 600])
    meta = {"task": name, "runId": run_id, "trigger": trigger, "command": task["command"],
            "workdir": str(WORKDIR), "sessionId": sid, "pid": pid or 999999,
            "pgid": None, "start": start.isoformat(timespec="seconds"), "status": status,
            "exitCode": {"success": 0, "failed": 1, "timeout": -15}.get(status),
            "durationSec": None if status == "running" else dur}
    if status != "running":
        meta["end"] = (start + timedelta(seconds=dur)).isoformat(timespec="seconds")
    meta.update(extra or {})
    (rdir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return rdir


def sleeper(name):
    """A detached process whose command line names the entry script and the task,
    so reconcile keeps the run `running` until it exits (2 h)."""
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(7200)",
                          str(SKILL / "clockmaster.py"), "_exec", name],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    return p.pid


def live_runners(name, n):
    """Real `run` processes against this data dir: parallel 2 -> 2 running, the
    rest queued. Started one by one so the queue order is the start order."""
    import store
    pids = []
    for i in range(n):
        before = len(store.run_dirs(name))
        p = subprocess.Popen([sys.executable, str(SKILL / "clockmaster.py"), "run", name, "--quiet"],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True, env=dict(os.environ))
        pids.append(p.pid)
        for _ in range(100):  # bounded: 10 s
            if len(store.run_dirs(name)) > before:
                break
            time.sleep(0.1)
        time.sleep(1.1)  # run ids carry the second: keep them apart
    return pids


def main(argv):
    force = "--force" in argv
    args = [a for a in argv if a != "--force"]
    data = Path(args[0]).expanduser().resolve() if args else Path(tempfile.mkdtemp(prefix="clockmaster-demo-"))
    if (data / "tasks").is_dir() and any((data / "tasks").glob("*.yaml")) and not force:
        sys.exit(f"{data} already has tasks — pass --force to add the demo anyway")
    os.environ["CLOCKMASTER_HOME"] = str(data)
    os.environ["CLOCKMASTER_SCHEDULER"] = "null"
    global WORKDIR
    WORKDIR = data / "home"
    WORKDIR.mkdir(parents=True, exist_ok=True)
    import taskdef
    import backends

    tasks_dir, runs = data / "tasks", data / "runs"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    for name, spec in TASKS.items():
        (tasks_dir / f"{name}.yaml").write_text(taskdef.new_text(spec), encoding="utf-8")

    rnd = random.Random(7)
    now = datetime.now().astimezone().replace(microsecond=0)
    for name, spec in TASKS.items():
        if spec.get("disabled"):
            continue
        cron = taskdef.from_file(tasks_dir / f"{name}.yaml").cron
        start = (now - timedelta(days=7)).replace(tzinfo=None)
        planned = [t for t in cron.walk(start, now.replace(tzinfo=None))][-14:]
        for t in planned:
            status = rnd.choices(["success", "failed", "timeout", "stopped"], [80, 12, 4, 4])[0]
            cost = round(rnd.uniform(0.02, 0.4), 4) if name == "inbox-triage" else None
            write_run(runs, name, spec, t.astimezone(), status, cost=cost,
                      session=name == "inbox-triage" and rnd.random() < 0.5)
    write_run(runs, "daily-report", TASKS["daily-report"], now - timedelta(days=2, hours=3), "killed")
    write_run(runs, "backup-db", TASKS["backup-db"], now - timedelta(hours=5), "failed", trigger="manual")
    write_run(runs, "inbox-triage", TASKS["inbox-triage"], now - timedelta(minutes=40), "success",
              trigger="manual", cost=0.1234, session=True)
    run = write_run(runs, "weekly-summary", TASKS["weekly-summary"], now - timedelta(minutes=3),
                    "running", trigger="manual", pid=sleeper("weekly-summary"))

    # queue history: two runs that waited, one skipped (queue full)
    rt = TASKS["render-thumbs"]
    for mins, waited in ((300, 0), (296, 240), (293, 420)):
        st = now - timedelta(minutes=mins)
        write_run(runs, "render-thumbs", rt, st + timedelta(seconds=waited), "success", trigger="manual",
                  extra={"queuedAt": st.isoformat(timespec="seconds")} if waited else None)
    sk = now - timedelta(minutes=290)
    write_run(runs, "render-thumbs", rt, sk, "skipped", trigger="manual",
              extra={"reason": "queue full (5 waiting)", "durationSec": 0, "end": sk.isoformat(timespec="seconds")})
    live = live_runners("render-thumbs", 4)

    be = backends.current()
    be.sync(taskdef.load_all())
    be.unregister(NOT_REGISTERED)

    print(f"seeded {len(TASKS)} tasks into {data}")
    print(f"running run: {run} (sleeper pid {json.loads((run / 'meta.json').read_text())['pid']})")
    print(f"\n  HOME={WORKDIR} CLOCKMASTER_HOME={data} CLOCKMASTER_SCHEDULER=null python3 {SKILL / 'clockmaster.py'} ui --fg")
    print("  (HOME points at the seeded home so inbox-triage runs find their claude transcripts)")
    print(f"render-thumbs runners (2 running, 2 queued): pids {' '.join(map(str, live))}")


if __name__ == "__main__":
    main(sys.argv[1:])
