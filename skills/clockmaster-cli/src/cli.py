"""Command line. Thin: parsing + printing; the work lives in ops/store/runner."""
import sys

import backends
import cron
import identity
import ops
import runner
import slots
import store
import taskdef
from errors import NotFound, UserError, ValidationError

APP = identity.APP

HELP = f"""{APP} — recurring local jobs on the OS's own scheduler
(macOS launchd · Linux systemd user timers · Windows Task Scheduler)

usage: {APP} <command> [args]

  list                          every task: schedule in plain words, scheduler
                                state, next run, last run
  add <name> --schedule '<cron>' --command '<shell>'
        [--workdir DIR] [--timeout 30m|2h|none] [--keep N|unlimited]
        [--description TEXT] [--notify off|on|failure] [--sound off|NAME]
        [--group NAME] [--parallel N] [--queue N] [--catchup true|false]
        [--disabled] [--force]
                                notify: banner when a run ends — failure (default)
                                = failed/timeout/killed only, on = every run
                                sound: macOS sound name (default Blow) or off
                                keep: how many past runs stay on disk (default 250)
                                group: folds tasks under one header in the UI
                                parallel: runs of this task at the same time
                                (default 1); more wait in line as `queued`
                                queue: how many may wait (default 20); one more
                                is recorded as `skipped` and never runs
                                catchup: false = a start missed while off or
                                asleep is dropped, not run late (default true)
  edit <name> --KEY VALUE ...   change keys (same flags as add; '' = default)
                                and sync
  show <name>                   one task: every setting in plain words
  sync                          apply tasks/*.yaml to the scheduler (after ANY edit)
  run <name>                    run now with live output (trigger: manual)
  runs <name> [-n N]            run history, newest first
  logs <name> [run-id]          output of the latest (or given) run
  stop <name> [run-id]          end a run that is still going, or take a queued
                                one out of the line -> stopped
  remove <name> [--purge-runs]  delete the task and unschedule it; history kept
                                unless --purge-runs
  ui [--port N] [--fg|--stop]   web UI on http://127.0.0.1:{identity.UI_PORT} (detached;
                                restarts a running one)
  ui --autostart [on|off]       keep the UI running as a service (macOS, Linux);
                                no value = show the state
  ui --share [HTTPS_PORT | --service [NAME]] [--allow LOGIN]
                                publish the UI on the tailnet (tailscale serve):
                                a Tailscale Service https://NAME.<tailnet>/ (NAME
                                default {identity.APP}; tagged hosts, their default)
                                or an https port of this node (default 8443);
                                only allowed Tailscale logins get in (default:
                                this node's owner); turns autostart on
  ui --unshare [HTTPS_PORT | --service [NAME]]
                                remove this UI's serve entries (all by default;
                                others untouched)
  migrate [--dry-run] [--from DIR]
                                adopt an old task-scheduler install: copy tasks,
                                history and notify config, retire its schedules

schedule = 5-field cron (minute hour day month weekday); when day AND weekday are
both set, a run needs both (unlike classic cron).

data: %DATA%
"""


# ---------- formatting ----------

def table(rows):
    widths = [max(len(str(r[i])) for r in rows) for i in range(len(rows[0]))]
    return "\n".join("  ".join(str(c).ljust(w) for c, w in zip(r, widths)).rstrip() for r in rows)


def fmt_delta(sec):
    sec = int(max(sec, 0))
    if sec < 60:
        return f"{sec}s"
    m = sec // 60
    if m < 60:
        return f"{m}m"
    h, m = divmod(m, 60)
    if h < 48:
        return f"{h}h {m:02d}m" if m else f"{h}h"
    return f"{h // 24}d"


def fmt_next(dt):
    if dt is None:
        return "never"
    return f"{dt.strftime('%Y-%m-%d %H:%M')} (in {fmt_delta((dt - store.now()).total_seconds())})"


def last_run(name):
    runs = store.recent(name, 1)
    if not runs:
        return "—"
    meta = runs[0]
    start = store.stamp(meta.get("start"))
    ago = fmt_delta((store.now() - start).total_seconds()) if start else "?"
    status = meta.get("status", "?")
    if status in ("running", "queued"):
        return f"{status} ({ago})"
    tag = {"skipped": "SKIPPED","success": "ok", "failed": f"FAILED({meta.get('exitCode')})", "timeout": "TIMEOUT",
           "killed": "KILLED", "stopped": "STOPPED"}.get(status, status)
    return f"{tag} {ago} ago"


def say(lines):
    for line in lines or []:
        print(line)


# ---------- commands ----------

def cmd_list(args):
    be = ops.backend()
    tasks = taskdef.load_all()
    if not tasks:
        print(f"no tasks yet — add one:\n  {APP} add <name> --schedule '0 9 * * *' --command '...'\n"
              f"or put a yaml into {identity.tasks_dir()} and run: {APP} sync")
    else:
        states = backends.states(be, tasks)
        grouped = any(t.group for t in tasks)
        rows = [["NAME", *(["GROUP"] if grouped else []), "ON", "SCHEDULE", "WHEN", "RUNS", be.label,
                 "NEXT RUN", "LAST RUN"]]
        for t in tasks:
            st = states[t.name]
            rows.append([t.name, *([t.group or "—"] if grouped else []), "yes" if t.enabled else "no",
                         t.schedule, cron.describe(t.cron), _runs_at_once(t),
                         st + (" (sync!)" if st in ops.DRIFT_STATES else ""),
                         fmt_next(ops.next_run(t)) if t.enabled else "—", last_run(t.name)])
        print(table(rows))
    orphans = ops.orphans(tasks)
    if orphans:
        print(f"\n(sync!) registered without a yaml: {', '.join(orphans)} — run `{APP} sync` or `{APP} remove <name>`")
    for note in be.notes():
        print(f"\nnote: {note}")
    return 0


def _runs_at_once(t):
    queued = slots.queued_count(store.queue_dir(t.name))
    return taskdef.parallel_text(t.parallel) + (f", {queued} queued" if queued else "")


FLAG_KEYS = ("schedule", "command", "workdir", "timeout", "keep", "description",
             "notify", "sound", "group", "parallel", "queue", "catchup")


def cmd_add(args):
    if not args or args[0].startswith("-"):
        raise ValidationError(f"usage: {APP} add <name> --schedule '<cron>' --command '<shell>' [options] — see `{APP} help`")
    name, rest = args[0], args[1:]
    flags = {f"--{k}": k for k in FLAG_KEYS}
    opts, force, i = {}, False, 0
    while i < len(rest):
        a = rest[i]
        if a == "--disabled":
            opts["disabled"] = True
            i += 1
        elif a == "--force":
            force = True
            i += 1
        elif a in flags and i + 1 < len(rest):
            opts[flags[a]] = rest[i + 1]
            i += 2
        else:
            raise ValidationError(f"unexpected argument '{a}'")
    for key in taskdef.REQUIRED:
        if not opts.get(key):
            raise ValidationError(f"--{key} is required")
    path = ops.add(name, opts, force)
    print(f"created {path}")
    return cmd_sync([])


def cmd_edit(args):
    if not args or args[0].startswith("-") or len(args) < 3:
        raise ValidationError(f"usage: {APP} edit <name> --KEY VALUE ... (keys: {', '.join(FLAG_KEYS)}, enabled)")
    name, rest, edits = args[0], args[1:], {}
    keys = FLAG_KEYS + ("enabled",)
    for i in range(0, len(rest), 2):
        key = rest[i][2:] if rest[i].startswith("--") else None
        if key not in keys or i + 1 >= len(rest):
            raise ValidationError(f"unexpected argument '{rest[i]}' — edit takes --KEY VALUE pairs: {', '.join(keys)}")
        edits[key] = rest[i + 1]
    task = ops.set_keys(name, edits)
    print(f"updated {task.path}: {', '.join(edits)}")
    return cmd_sync([])


def cmd_show(args):
    if not args:
        raise ValidationError(f"usage: {APP} show <name>")
    t = taskdef.load(args[0])
    queued = slots.queued_count(store.queue_dir(t.name))
    rows = [
        ("schedule", f"{t.schedule}  ({cron.describe(t.cron)})"),
        ("enabled", "yes" if t.enabled else "no"),
        ("next run", fmt_next(ops.next_run(t))),
        ("command", t.command), ("workdir", str(t.workdir)),
        ("timeout", store.fmt_dur(t.timeout) if t.timeout else "none"),
        ("keep", "unlimited" if t.keep is None else f"{t.keep} runs"),
        ("parallel", taskdef.parallel_text(t.parallel)),
        ("queue", f"up to {t.queue} waiting" + (f" ({queued} queued now)" if queued else "")
         if t.queue else "none (a run that finds no free slot is skipped)"),
        ("catchup", "yes (a missed start runs late)" if t.catchup else "no (a missed start is dropped)"),
        ("notify", t.notify), ("sound", t.sound),
        *([("group", t.group)] if t.group else []),
        *([("description", t.description)] if t.description else []),
        ("last run", last_run(t.name)), ("file", str(t.path)),
    ]
    print(table([[k, v] for k, v in rows]))
    return 0


def cmd_sync(args):
    ok, lines = ops.sync()
    say(lines)
    return 0 if ok else 2


def cmd_run(args):
    if not args:
        raise ValidationError(f"usage: {APP} run <name>")
    return runner.exec_task(args[0], "manual", echo="--quiet" not in args)


def cmd_exec(args):
    if not args:
        raise ValidationError(f"usage: {APP} _exec <name>")
    return runner.exec_scheduled(args[0])


def _need_history(name):
    if taskdef.find(name) is None and not store.run_dirs(name):
        raise NotFound(f"no such task '{name}'")


def cmd_runs(args):
    if not args:
        raise ValidationError(f"usage: {APP} runs <name> [-n N]")
    name, n = args[0], 15
    if "-n" in args:
        try:
            n = int(args[args.index("-n") + 1])
        except (IndexError, ValueError):
            raise ValidationError("-n needs a number")
    _need_history(name)
    runs = store.recent(name, n)
    if not runs:
        print(f"no runs yet for '{name}'")
        return 0
    rows = [["RUN ID", "TRIGGER", "STATUS", "EXIT", "DURATION", "STARTED"]]
    for m in runs:
        d, rc = m.get("durationSec"), m.get("exitCode")
        rows.append([m["runId"], m.get("trigger", "?"), m.get("status", "?"), "" if rc is None else rc,
                     store.fmt_dur(d) if d is not None else "", m.get("start", "?")])
    print(table(rows))
    return 0


def cmd_logs(args):
    if not args:
        raise ValidationError(f"usage: {APP} logs <name> [run-id]")
    name = args[0]
    _need_history(name)
    dirs = store.run_dirs(name)
    if not dirs:
        raise NotFound(f"no runs yet for '{name}'")
    rdir = store.run_dir(name, args[1]) if len(args) > 1 else dirs[0]
    if not rdir.is_dir():
        raise NotFound(f"no run '{args[1]}' for task '{name}'")
    m = store.read(rdir) or {}
    print(f"# {name} / {rdir.name} — {m.get('status', '?')} (exit {m.get('exitCode')}), "
          f"trigger {m.get('trigger', '?')}, started {m.get('start', '?')}", file=sys.stderr)
    log = rdir / "output.log"
    if log.exists():
        sys.stdout.flush()
        sys.stdout.buffer.write(log.read_bytes())
    return 0


def cmd_stop(args):
    if not args:
        raise ValidationError(f"usage: {APP} stop <name> [run-id]")
    rdir = store.pick_to_stop(args[0], args[1] if len(args) > 1 else None)
    _, note = store.stop(rdir)
    print(f"{args[0]} / {rdir.name}: {note}")
    return 0


def cmd_remove(args):
    if not args or args[0].startswith("-"):
        raise ValidationError(f"usage: {APP} remove <name> [--purge-runs]")
    name, purge = args[0], "--purge-runs" in args
    had = taskdef.path_of(name).is_file()
    ok, lines = ops.remove(name, purge)
    if had:
        print(f"deleted {taskdef.path_of(name)}")
    say(lines)
    if purge:
        print(f"purged the run history of '{name}'")
    return 0 if ok else 2


def cmd_ui(args):
    from web import control
    say(control.run(args))
    return 0


def cmd_migrate(args):
    import migrate
    return migrate.main(args)


COMMANDS = {"list": cmd_list, "add": cmd_add, "edit": cmd_edit, "show": cmd_show, "sync": cmd_sync, "run": cmd_run, "_exec": cmd_exec,
            "runs": cmd_runs, "logs": cmd_logs, "stop": cmd_stop, "remove": cmd_remove,
            "ui": cmd_ui, "migrate": cmd_migrate}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # `<cmd> --help` must print help, never act (`ui --help` used to start the UI)
    if not argv or argv[0] == "help" or any(a in ("-h", "--help") for a in argv):
        print(HELP.replace("%DATA%", str(identity.data_dir())))
        return 0
    fn = COMMANDS.get(argv[0])
    if fn is None:
        print(f"error: unknown command '{argv[0]}' — see: {APP} help", file=sys.stderr)
        return 2
    try:
        return fn(argv[1:]) or 0
    except UserError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
