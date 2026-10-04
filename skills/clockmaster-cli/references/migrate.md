# Migrating from task-scheduler

`clockmaster migrate --dry-run` first, then `clockmaster migrate`. Source: `--from DIR`, else `$TASK_SCHEDULER_HOME`, else `~/.claude/task-scheduler`.

- Copies `tasks/*.yaml`, `runs/**`, `notify.yaml`, `memory.md`, `memory/**`. Task yaml is the same format: nothing to convert.
- Identical file already here = skipped. Different file = conflict: kept, listed with `!`, never overwritten - compare by hand.
- A run still `running` is skipped; run migrate again after it ends.
- Retires the old schedules: macOS agents `com.claude.task-scheduler.*` + `com.claude.task-scheduler-ui` (bootout + delete), Windows tasks in `\claude-task-scheduler`. The old tool had no Linux scheduler.
- Then syncs: tasks run under clockmaster from the next fire.
- The old dir is only read. Delete it (and the old skill) yourself once happy.
- Re-running is harmless. Exit: 0 done, 1 conflicts to review, 2 sync failed (the copy is done; fix and `clockmaster sync`).
- Not carried over: the old UI port 7787 (now 7788) and `ui --autostart` - turn it on again with `clockmaster ui --autostart on`.
- Commands referring to `$TASK_SESSION_ID` and `TASK_COST_USD=` keep working: same names.
