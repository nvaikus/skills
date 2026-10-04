# Windows Task Scheduler

- One task per task in folder `\clockmaster`, registered from generated XML (`schtasks /create /xml`, UTF-16 + BOM, no admin: InteractiveToken + LeastPrivilege). The folder is created automatically.
- `StartWhenAvailable` = sleep/off catch-up: a missed run fires LATE, at a minute the cron never matches. So `_exec` re-checks only the DATE fields.
- StartBoundary is pinned to 2000-01-01: it does NOT replay old occurrences (live-proven) and keeps the XML byte-stable.
- XML cannot AND day-of-month with weekday, nor filter a weekly schedule by month: the looser trigger is registered and `_exec` exits silently on a non-matching date, recording nothing. Gap: a catch-up slipping past midnight on such a cron is dropped.
- No "every hour" wildcard: `*/N * * * *` and `0 * * * *` become one trigger with `<Repetition>`; other `*`-hour crons cost one trigger per hour; over 512 triggers is refused (`0-30 * * * *`).
- Drift is measured against `<data>/schtasks-xml/<task>.xml` (written at registration), never against `schtasks /query /xml` (re-serialized: own order, `\r\r\n`, console codepage). A task disabled in taskschd.msc shows `unloaded (sync!)`; `sync` re-enables it.
- `schtasks /delete /tn "\folder\*"` fails: one task at a time. An emptied folder stays; harmless.
- The action runs `pythonw.exe` (no console flash, no stdio): `_exec` writes to `<data>/scheduler-io/<task>.log`. Non-empty = the CLI failed, not the task.
- Scheduled runs get env from the registry, not a terminal: a `CLOCKMASTER_HOME` set in a shell never reaches them - set it as a user env var. Task cwd defaults to system32; the runner cd's to the workdir.
- Commands run under `cmd /d /s /c "<command>"` passed as a raw STRING: `%VAR%`, not `$VAR`. Never a Popen list - list2cmdline's `\"` silently truncates quoted args in cmd.exe.
- Timeout/stop = `taskkill /PID <shell> /T`, then `/T /F`. `/T` walks the tree from a LIVE parent: never kill the shell alone.
- Boot time = CIM `LastBootUpTime` (NOT GetTickCount64, which excludes sleep and kills live runs on reconcile).
- Git Bash mangles `/flags` and `\paths`: call schtasks from PowerShell, or `MSYS_NO_PATHCONV=1`.
- Inspect: `schtasks /query /tn "\clockmaster\<task>" /v /fo LIST` or taskschd.msc. Its own history log is off by default: `clockmaster runs <task>` is the history.
- `ui --autostart` is not available on Windows yet; `clockmaster ui` starts it for the session.
- Claude transcripts munge the drive too: `C:\Users\me` → `C--Users-me`. Resume opens Windows Terminal (else cmd).
