# clockmaster — developer notes

Name: `clockmaster`. The name lives in
`src/identity.py` ONLY (plus: this folder name, the entry script filename
`clockmaster.py`, SKILL.md frontmatter/title, README row). Everything else —
data dir, env override, launchd labels, systemd unit names, Windows task
folder, UI title (served by `/api/app`), wrapper — derives from it.

Zero runtime deps: python3 stdlib + the committed frontend build in `src/web/dist/`.

## Map

```
clockmaster.py            entry: puts src/ on sys.path, calls cli.main()
src/identity.py         APP name + every derived name/path (single rename point)
src/taskdef.py          flat yaml read / validate / line-preserving key edits
src/cron.py             cron parse + match (day AND weekday) + next + planned walk + plain words + upcoming (editor preview)
src/store.py            runs/<task>/<run-id>/{meta.json,output.log}, prune, reconcile
src/procs.py            pid/cmdline/boot time/kill group/detach/shell argv per OS
src/runner.py           one run: queue gate, spawn, echo, timeout, record, notify
src/slots.py            per-task run slots + FIFO queue via OS file locks (runs/<task>/.queue/)
src/errors.py           UserError(msg, where) -> ValidationError 400 / NotFound 404 / Conflict 409; CLI: `error: …`, exit 2
src/ops.py              shared verbs for CLI + API: sync, add/edit/rename/remove, task_json, run_json, resume
src/backends/           one module per OS scheduler, same interface (see below)
  __init__.py           current() -> backend for sys.platform
  launchd.py            macOS LaunchAgents
  systemd.py            Linux systemd --user timers
  schtasks.py           Windows Task Scheduler
  null.py               CLOCKMASTER_SCHEDULER=null (tests, demo): JSON registry in the data dir, touches no OS scheduler
src/notify/             pluggable channels; gate (notify: off|on|failure) applied once
  __init__.py           dispatch(task, run) -> every enabled channel, best effort
  desktop_mac.py        notifier.app bundle (see old traps below)
  desktop_linux.py      notify-send when a desktop session exists; else no-op + note
  desktop_win.py        WinRT toast via PowerShell
  teams.py              <data>/notify.yaml -> m365-cli channel-post
src/cost.py             claude transcript pricing + TASK_COST_USD= lines
src/migrate.py          adopt an old task-scheduler install
src/cli.py              argument parsing + command handlers (thin)
src/web/server.py       stdlib HTTP server (ROUTES table), lifecycle, self re-exec
src/web/api.py          handlers -> JSON (contract below)
src/web/control.py      `ui` lifecycle: detached start, evict own instance on the port, --stop, --autostart
src/web/peer.py         Linux: connecting socket's owner uid from /proc/net/tcp{,6}; only own uid or root (then gate.py) pass
src/web/gate.py         per-request owner gate: proxied => allowed Tailscale-User-Login; no cross-site writes
src/web/tailnet.py      `ui --share/--unshare`: tailscale serve entry (svc:NAME or node port), allow file, autostart, gate probe
dev/demo_seed.py        fake data dir (tasks, runs, a transcript) for UI work with the null backend
src/web/frontend/       React 19 + TS + Vite + Tailwind v4 (build -> ../dist, COMMITTED)
dev/tests/              python3 -m unittest discover -s dev/tests
```

## Names (identity.py)

| thing | value |
|---|---|
| APP | `clockmaster` |
| data dir | `~/.claude/clockmaster/` (env `CLOCKMASTER_HOME`) |
| launchd task label | `com.claude.clockmaster.<task>` ; UI agent `com.claude.clockmaster-ui` (OUTSIDE the task prefix — orphan sweep) |
| systemd units | `clockmaster.<task>.service` + `.timer` ; UI `clockmaster-ui.service` (outside the `clockmaster.` prefix) in `$XDG_CONFIG_HOME/systemd/user/` |
| Windows | task folder `\clockmaster` |
| UI | port 7788 (old tool keeps 7787, both can run), title = APP |

## Backend interface (backends/*.py)

| member | meaning |
|---|---|
| `name`, `label` | `"systemd"`; column header in `list` (`SYSTEMD`, `LAUNCHD`, `SCHEDULER`) |
| `state(task)` / `states(tasks) -> {name: state}` | `"ok"\|"off"\|"missing"\|"stale"\|"unloaded"`; `states` batches (one systemctl call for all timers) |
| `registered(name)`, `registered_names()` | by prefix on disk / in the folder |
| `sync(tasks) -> [lines]` | register changed, re-load unloaded, unregister disabled + orphans; idempotent |
| `unregister(name)`, `notes() -> [str]` | env warnings for `list`/API (linger, no bus) |
| `exec_guard(task, now) -> bool` | False = `_exec` exits silently (Windows date re-check) |
| `ui_autostart_state() -> None\|{port, pid, detail}` | None = off |
| `ui_autostart_on(port)` / `_off()` / `_restart(port)` / `_stop()` / `_hint() -> str` | write+enable+start, no readiness wait (control.py waits); Windows/null `on` raises ValidationError |

Choice: `CLOCKMASTER_SCHEDULER` env (`null`, `systemd`, …) else by `sys.platform`.

## HTTP API contract (frontend depends on it; camelCase JSON; 127.0.0.1 only; gate.py may answer 403 to anything)

- `GET /api/app` → `{app, platform: "linux"|"darwin"|"win32", backend: "systemd"|"launchd"|"schtasks", dataDir, notes: string[], sounds: string[], canOpenTerminal: bool, notifyChannels: string[]}` (notifyChannels = plain names a finished run reaches now: "Desktop", "Teams", "Telegram")
- `GET /api/drift` → `{drift: number}` — tasks the scheduler disagrees with + scheduler entries with no task (header "out of sync").
- `GET /api/tasks` → `Task[]`: `{name, group ("" = none), description, enabled, notify: "off"|"on"|"failure", sound, schedule, scheduleText (plain words, e.g. "every weekday at 9:00"), command, workdir, timeoutSec: number|null, keep: number|null (resolved; null = unlimited), parallel: number (≥1), queue: number (≥0), queued: number (waiting now), state: "ok"|"off"|"missing"|"stale"|"unloaded", drift: bool, nextRun: iso|null, lastRun: Run|null, lastRuns: [{runId, status, start, durationSec, trigger, queuedAt?, reason?}] (newest first, max 20; the task row's run strip), avgDurationSec: number|null (mean of the succeeded/failed among the last 20)}`
- `GET /api/tasks/:name` → Task + `{yaml, spentUsd: number|null}`
- `GET /api/schedule?cron=` → `{cron (whitespace-normalized), text, next: iso[] (up to 3)}`; 400 on a bad cron. Editor's live preview — the one cron parser stays in python.
- `GET /api/tasks/:name/runs?n=50` → `Run[]`: `{task, runId, trigger: "manual"|"schedule", command, workdir?, sessionId?, start, end?, status: "queued"|"running"|"success"|"failed"|"timeout"|"killed"|"stopped"|"skipped", exitCode: number|null, durationSec: number|null, hasSession: bool, costUsd: number|null, queuedAt?: iso (arrived with no free slot; start = actual start), reason?: string (skipped: "queue full (N waiting)")}` — queued: start = queuedAt, no end; never started (skipped / removed from the queue) = start = end, durationSec 0
- `GET /api/tasks/:name/runs/:id/log` → text/plain
- `GET /api/runs/search?q=&limit=20` → `[{task, runId, status, start, durationSec}]`: runs whose run id contains q (case-insensitive), newest first, max limit (1–200); only tasks that still have a task file; lists run dirs, reads hits' meta.json only, never logs. Blank q → `[]`.
- `GET /api/timeline?from=iso&to=iso` → `[{task, group, enabled, runs: [{runId, start, end|null, durationSec, status, trigger, exitCode, queuedAt?, reason?}], planned: iso[], plannedTruncated: bool, plannedEvery: number, avgDurationSec: number|null}]` (window clamped to 92 days; over 1000 starts/task the server sends every `plannedEvery`-th across the whole window, never just the first 1000)
- `GET /api/notify-click` → `{}` or `{task, runId}` (consumed once, TTL 120 s)
- `POST /api/tasks/:name` body = changed keys of `name, schedule, command, workdir, timeout, keep, description, group, parallel, queue` (blank optional = drop key → default) → `{ok, name, syncOutput}`; 400 validation text, 409 rename collision
- `DELETE /api/tasks/:name[?purge-runs=1]` → `{ok, deleted, purgedRuns, syncOutput}`
- `POST /api/tasks/:name/run` → 202 `{started}` (run appears on disk ~0.5 s later; poll)
- `POST /api/tasks/:name/enabled {enabled}` → `{ok, enabled, syncOutput}`
- `POST /api/tasks/:name/notify {notify}` → `{ok, notify}` ; `POST .../sound {sound}` → `{ok, sound}`
- `POST /api/tasks/:name/runs/:id/stop` → `{run, note}` (queued run: removed from the queue, status stopped)
- `GET /api/tasks/:name/runs/:id/resume` → `{command, canOpen: bool}` (read-only: what a resume click would do; canOpen = transcript exists AND a terminal can be opened)
- `POST /api/tasks/:name/runs/:id/resume` → `{opened: bool, command: string, note}` (command = shell line to resume; opened=false where no terminal can be opened, e.g. headless Linux)
- `POST /api/sync` → `{ok, output}`
- Errors: `{error}` with 400/404/409/500.

## Traps (measured)

- Tests: `dev/tests/base.py` Case isolates HOME, XDG_CONFIG_HOME, CLOCKMASTER_HOME, PATH (fake `systemctl`/`loginctl` in a tmp bin) and defaults the scheduler to null. A sync against the real user manager deletes real `clockmaster.*` units (orphan sweep) — never drop that isolation.
- Sync from a clone/worktree rewrites the real units to point at THAT checkout's `clockmaster.py`. Only an explicit `CLOCKMASTER_HOME` travels into units/plists; the default data dir is never baked in.
- Zombies: the UI server is the parent of runners it starts. A finished runner stays a zombie, `kill(pid, 0)` still succeeds, and `stop` waited out the 10 s TERM grace. `procs.alive` reaps own children (`waitpid WNOHANG`) and treats state `Z` as dead.
- Linux shell: `bash -lc` skips Debian `.bashrc` (returns unless interactive) → keys missing. `-lic` without a tty prints two job-control lines; `+m` does not help. Fix in `procs.shell_spawn`: stderr → /dev/null at start, command begins `exec 2>&<logfd>`, runs in a subshell (no "logout" line, rc kept). Rc-file errors are the accepted loss.
- systemd: ExecStart words double-quoted with `%`/`$` doubled; `StandardOutput=append:` takes no quoting → a data dir with whitespace falls back to the journal. TimeoutStartSec=infinity (the runner owns the timeout). Disabling a task stops the timer only, never the service.
- systemd UI unit: KillMode=process, or every restart/off kills runs the UI started (they are in its cgroup). `ui --fg` must `os.execv` the server so MainPID is the listener.
- Cron next/planned walk: naive local time, day/hour skipping, scan 5 years (Feb 29 on a Monday is beyond it → None). `systemd-analyze calendar` agrees with `cron.oncalendar` (tested when present).
- launchd/schtasks caps: 512 intervals/triggers; `*/7` minutes on Windows is 216 triggers (fine), `* 0-9 * * *` is refused.
- schtasks XML cache is UTF-16 with CRLF: byte compare, never text compare against `/query /xml`.
- Gate: tailscale serve proxies from 127.0.0.1, so the peer address proves nothing; "proxied" = any forwarding/Tailscale header or a non-local Host. Never relax that to "has X-Forwarded-For" alone. Test servers: `serve_forever(poll_interval=0.05)`, else each tearDown costs 0.5 s.
- Peer uid: match the row with local = client addr AND remote = server addr AND inode != 0. Orphaned/TIME_WAIT rows read uid 0 — trusting them lets a client that sends a POST and closes pass as root. Lookup failure on Linux = 403 (fail closed).
- Reconcile writes are swallowed and never notify; renamed task dirs override `meta.task`.
- Queue (slots.py): flock is per open file, so two Gates in one process conflict (tests rely on it). Liveness = "can I take the lock"; a dead runner frees its slot/place with no cleanup. `.wait` files are created+locked and deleted only under `mutex`, else a probe sees a new file unlocked and unlinks a live place. `runs/<task>/.queue` is a dot dir: `store.run_dirs` skips it.
- Scheduler overlap: the runner blocks inside the unit/job while queued, so the OS drops a tick while one is active (systemd oneshot `start` on an active unit = no-op; launchd one instance per label; schtasks `IgnoreNew`). Scheduled ticks never stack; manual/UI/API runs spawn the runner directly and queue. `parallel` is re-read from the yaml on every poll (≤1 s backoff, head of line 0.2 s).
