# Pending runs, restart, CLI → bot inbox

Read when touching `state.json` / `Store`, `restore()`, `claude-tg restart` / `install`, or `inbox.py` (`spawn` / `send`).

- Pending requests live in `state.json` until done; SIGTERM → `Bridge.shutdown` kills runs but keeps them; `restore()` re-runs on start. `claude-tg restart` / `install` wait for an empty `pending`. Inside a bot run (`CLAUDE_TG_RUN_TOPIC` set) `restart` would wait for itself: it detaches a waiter (`systemd-run --user`: `KillMode=control-group` would kill a plain child with the old bot) that restarts when idle and reports to the topic via `--report`.
- Scripts never write state.json (the bot rewrites it from memory): `spawn`/`send` post the prompt (or the `--show` line) as a bot message, then drop a file in `STATE_DIR/inbox/`; `Bridge._inbox_loop` (1 s) → `inbox.apply` → topic fields (`cwd`, `title`, `icon` = base icon, `system` → `--append-system-prompt`, `settings` → `--settings` (missing/not JSON at run time → run refused, `why.settings`: fail closed), `quiet`) + `Worker.put` of a synthetic owner message keyed by the posted message id. Bad file → `inbox/bad/`.
