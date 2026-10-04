# macOS launchd

- One LaunchAgent per task: `~/Library/LaunchAgents/com.claude.clockmaster.<task>.plist`. Sync deletes every plist with that prefix that has no yaml behind it.
- The agent runs `/bin/zsh -lic "exec <clockmaster.py> _exec <task>"`. launchd's own env is bare (PATH=/usr/bin:/bin); `-lic` loads .zprofile AND .zshrc (`-lc` skips .zshrc and its exported keys). tty-only .zshrc lines print noise: guard them with `test -t 1`. TERM=dumb is set to keep shell integrations quiet.
- StartCalendarInterval = cartesian product of the cron fields, max 512 entries (else `add` refuses). launchd ANDs day and weekday - the cron meaning here.
- Missed while ASLEEP → one run on wake. Missed while powered OFF → nothing at boot.
- One label = one instance: a fire is silently skipped while the previous run lives. Hence the 2h default timeout.
- Load = `launchctl bootstrap gui/<uid> <plist>`, unload = `bootout gui/<uid>/<label>`. Bootstrap on a loaded label fails "5: Input/output error"; `launchctl print` rc 0 = loaded. Loaded-ness is part of `state`: plist present but not loaded = `unloaded (sync!)`.
- `<data>/launchd-io/<task>.log` = launchd's stdout/stderr: non-empty means the CLI failed around the run; task output is in the run's output.log.
- `ui --autostart on` = agent `com.claude.clockmaster-ui` (outside the task prefix, safe from the sweep), KeepAlive. A SIGTERM is undone by launchd: stop = `bootout` (`ui --stop` keeps the plist), restart = `kickstart -k`.

## Privacy (TCC) can hang a run

- `~/Documents`, `~/Desktop`, `~/Downloads` (and iCloud Drive, removable volumes) are protected. The first access from a launchd process raises a consent prompt NOBODY sees: the run blocks until its timeout, then `Operation not permitted`. A login profile (`brew shellenv`) touching the cwd counts.
- Measured: `workdir: ~/Documents/...` sat `running` 2.5h; log had `The current working directory must be readable ... to run brew`.
- `sync` prints `! <task>: workdir is under ~/Documents ...` for a workdir or command path resolving there (symlinks followed).
- Fix, best first: keep workdir and scripts outside those folders; or System Settings > Privacy & Security > Full Disk Access (or Files and Folders) for the python3 the run actually uses (`zsh -lic 'command -v python3'`; the entry's shebang resolves it) - NOT Terminal, whose grant a launchd job does not inherit.
- Homebrew python shows TWO clients (`Python` and `python3.12`); the deny lands on the stub - grant both. Re-check after `brew upgrade python`. Reset a recorded deny: `tccutil reset SystemPolicyDocumentsFolder org.python.python`.
- Probe: `clockmaster add zz-tcc-probe --schedule '0 0 1 1 *' --workdir <folder> --command 'ls && echo OK'`, then `launchctl kickstart gui/$UID/com.claude.clockmaster.zz-tcc-probe`, `clockmaster logs zz-tcc-probe`.

## Claude sessions

- Transcript: `~/.claude/projects/<cwd with every non-alphanumeric char → ->/<session-id>.jsonl`. Exists only when the command passed `--session-id "$TASK_SESSION_ID"`. Resume runs `claude --resume <id>` from the task workdir in a new iTerm window.
