---
name: clockmaster-cli
description: Run local jobs on a schedule - claude -p runs, scripts, any shell command - through the computer's own scheduler (macOS launchd, Linux systemd user timers, Windows Task Scheduler), with run history, logs, desktop/Teams/Telegram notifications, claude cost per run and a local web UI. Zero-dependency python CLI. Use when the user wants something to run daily/hourly/every N minutes on this machine, to list scheduled jobs, check what ran and why it failed, run a job now, stop, disable or remove one, or move from the old task-scheduler skill. Triggers - schedule a task, run every morning, recurring job, cron a script, launchd, systemd timer, Task Scheduler, schtasks, запусти по расписанию, каждый день в 9, шедул.
---

# clockmaster-cli

The computer's own scheduler fires the jobs - launchd (macOS), systemd user timers (Linux), Task Scheduler (Windows). No daemon to keep alive. Survives reboots; a run missed while asleep or off runs once when the machine is back.

CLI: `clockmaster.py` at the skill root (`clockmaster` wrapper). Everything goes through it.

```
clockmaster list                                   # every task: schedule in words, scheduler state, next + last run
clockmaster add daily-report --schedule '0 9 * * 1-5' --command 'claude -p "/report" --session-id "$TASK_SESSION_ID"'
      [--workdir DIR] [--timeout 30m|2h|none] [--keep N|unlimited] [--description TEXT]
      [--notify off|on|failure] [--sound off|NAME] [--group NAME] [--parallel N] [--queue N] [--disabled]
clockmaster edit <name> --KEY VALUE ...             # same keys as add (+ --enabled true|false), then sync
clockmaster show <name>                            # one task in plain words
clockmaster run <name>                             # run now, live output (trigger manual)
clockmaster runs <name> [-n N]  |  logs <name> [run-id]  |  stop <name> [run-id]
clockmaster sync                                   # after ANY yaml edit
clockmaster remove <name> [--purge-runs]
clockmaster ui [--fg|--stop] [--autostart on|off]  # web UI, http://127.0.0.1:7788
clockmaster ui --share [HTTPS_PORT | --service [NAME]] [--allow LOGIN] | --unshare   # phone access over Tailscale, owner-only
clockmaster migrate [--dry-run]                    # adopt the old task-scheduler install
```

Schedule = 5-field cron: minute hour day month weekday. `list` and the UI repeat it in plain words ("every weekday at 9:00") - show those to the user. Day AND weekday both set = both must match (classic cron: either).

## Files

- `~/.claude/clockmaster/` (env `CLOCKMASTER_HOME`): `tasks/<name>.yaml`, `runs/<name>/<run-id>/{meta.json,output.log}`, `ui.log`, `notify.yaml`, `notify.log`.
- Task yaml = flat `key: value` lines: `schedule`, `command` (required); `workdir` (default home), `timeout` (2h), `keep` (250), `enabled`, `description`, `notify` (failure), `sound`, `group`, `parallel` (1), `queue` (20), `catchup` (true). File name = task name (kebab-case); `_*.yaml` ignored.
- Scheduler entries are generated: never edit them by hand, edit the yaml and `sync`.

## Rules

- `list` shows `(sync!)` when yaml and scheduler drifted: run `sync`.
- Headless `claude -p` cannot answer permission prompts: pre-allow tools (settings allowlist / `--permission-mode`), else the run hangs until its timeout.
- Pass `--session-id "$TASK_SESSION_ID"` (Windows: `%TASK_SESSION_ID%`) to a claude command: the run gets a cost and a Resume button.
- A script calling `claude -p` inside prints `TASK_COST_USD=<float>` after each call (from `--output-format json` `total_cost_usd`); the run's cost sums them. No `--session-id` for inner calls.
- Run statuses: queued, running, success, failed, timeout, stopped (`stop`), killed (runner died: reboot, kill -9), skipped (queue full; notifies like a failure). Missing workdir = failed, exit 78.
- `parallel` = runs of one task at the same time, default 1 (before: unlimited - set `parallel: N` where overlap is wanted). A run with no free slot is `queued`, FIFO, across every trigger (schedule, `run`, UI); the timeout counts from its actual start. More than `queue` waiting (default 20, 0 = no queue) = `skipped`. `stop` on a queued run removes it from the queue. Disabling a task does not cancel runs already queued.
- `catchup: false` (`--catchup false`): a start missed while off/asleep is dropped, not run late; a scheduled start more than 2 min past its minute is ignored (no run recorded). Default true = runs once on wake/boot.
- Scheduled ticks never stack: while a scheduled run runs or waits, the OS scheduler drops the next tick (systemd oneshot unit still active, launchd one instance per job, Windows `IgnoreNew`). Manual runs queue.
- Linux: timers fire only while the user has a session unless linger is on - `list` says so; offer `loginctl enable-linger $USER`.

| when | read |
|---|---|
| macOS: env, sleep catch-up, a run stuck in `running` under ~/Documents, notifier permission | `references/launchd.md` |
| Linux: timers, linger, no user bus (sudo/su/containers), shell env, UI service | `references/systemd.md` |
| Windows: triggers, cmd quoting, pythonw, io log | `references/windows.md` |
| banners, sounds, Teams channel posts, Telegram, notify.log | `references/notify.md` |
| UI from a phone / another device, `ui --share`, Tailscale Services (svc:NAME), tagged host, a 403 from the UI | `references/tailnet.md` |
| moving from the old task-scheduler skill | `references/migrate.md` |

## Memory

`~/.claude/clockmaster/memory.md`: local lessons, outside the skill (updates keep it). Read first; create on first write. Cost a question, retry or context → one imperative line now; why only if it prevents a mistake. Situational → `memory/<topic>.md` behind a `<trigger> → file` line. Every-user fact → skill defect (unsure → note; proven → move it in).

- Typical entries: which tasks the user owns and why, workdirs that need special env, channels they post to.

## Fix on friction

Gap, confusing/flooding/noisy output, stale text = skill defect; no silent workarounds. Small → fix now. Large → background `opus` teammate, one-message ticket (fact, proving command, output) fixing the faulty layer: SKILL.md, references/, scripts/, tool. Continue only if unblocked. Tracked (`skilltap status`) → edit its clone, pull, push; else in place.

- Code changes: read `src/CLAUDE.md` first; `python3 -m unittest discover -s dev/tests` must stay green.

> Source: https://github.com/nvaikus/skills/blob/main/skills/clockmaster-cli/SKILL.md
> Install via skilltap for auto-updates: https://github.com/nvaikus/skills/blob/main/skills/skilltap/SKILL.md
