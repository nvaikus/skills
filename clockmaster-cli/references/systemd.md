# Linux systemd user timers

- Per task, in `~/.config/systemd/user/` (`$XDG_CONFIG_HOME`): `clockmaster.<task>.service` (Type=oneshot, `python3 clockmaster.py _exec <task>`, TimeoutStartSec=infinity - the runner owns the timeout) + `clockmaster.<task>.timer` (OnCalendar, Persistent=true, AccuracySec=1s). Sync removes every `clockmaster.*` unit without a yaml.
- OnCalendar ANDs weekday and date = the cron meaning here. Check a conversion: `systemd-analyze calendar --iterations=5 '<OnCalendar>'`. Times = the user manager's timezone (system zone unless TZ is in `systemctl --user show-environment`).
- Persistent=true: a start missed while off/asleep runs once at the next boot or login. `catchup: false` → Persistent=false (plus the runner's on-time check).
- Inspect: `systemctl --user list-timers 'clockmaster.*'`, `systemctl --user status clockmaster.<task>.timer`, `journalctl --user -u clockmaster.<task>.service`.
- `<data>/scheduler-io/<task>.log` = the service's stdout/stderr: non-empty means the CLI failed around the run; task output is in the run's output.log.
- `remove`/disable stops the timer only, never the service: a run in flight finishes.

## Linger and the user bus

- Linger off (default): the user manager lives only while the user has a session. After a reboot nothing fires until login; logout stops timers. `list`/`sync` print a note. Fix: `loginctl enable-linger $USER` (polkit may ask for admin).
- No user bus (`Failed to connect to bus`): `sudo -u`, `su`, cron, containers. Fix: log in through a real session (ssh/console), or `export XDG_RUNTIME_DIR=/run/user/$(id -u)` when the manager runs. `sync` refuses with that hint and changes nothing.
- No systemd at all (some containers, WSL1): no backend. Workaround: one crontab line per task, `<cron> python3 <skill>/clockmaster.py _exec <task>` - history, notify and cost still work.

## Task shell

- The command runs in the user's login shell from passwd (not `$SHELL`). Debian/Ubuntu `.bashrc` returns early unless interactive, so bash and zsh run `-lic`: keys exported in .bashrc are present.
- bash `-i` without a tty prints "cannot set terminal process group" + "no job control". The shell starts with stderr on /dev/null, the command re-points it to the log first: only rc-file errors are lost. The command runs in a subshell, so its own `exit` code still lands and no "logout" line appears.
- Other shells (dash, fish, ...): plain `-lc`.

## Web UI service

- `ui --autostart on` = `clockmaster-ui.service` (outside the task prefix), Restart=always, WantedBy=default.target. KillMode=process: restarting the UI never kills runs it started (live-verified). `off` disables + deletes the unit and keeps a detached UI for the session.
- With linger off it starts at login only.

## Banners and resume

- `notify-send` only when a desktop session exists (DISPLAY/WAYLAND_DISPLAY in the env or in the user manager's env). Headless = silent no-op + one `notify.log` line.
- Resume opens `x-terminal-emulator` when a display exists; otherwise the UI shows the `claude --resume` command to copy.
