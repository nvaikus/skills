# notify, triage, spawn / send (scripts and jobs driving the bot)

Per-command facts: `claude-tg <cmd> -h` (`notify`, `notify-delete`, `triage`, `spawn`, `send`, `alive`, `topic-icon`, `topic-settings`, `topic-delete`). Here only the choice between them.

- No claude turn → `notify`: plain Bot API send, no service needed; one topic per domain via config `notify_topics` (`setup.md`). Status-only line into a task topic = `notify --thread ID --silent`.
- A claude turn → `spawn` (new topic) / `send` (existing topic): need the running service (queued while it is down); `alive` tells whether a run is live there.
- A notification can still lead to a turn: the owner replies to it (session in that topic, notification quoted), or auto-triage (`triage on`) opens a 🔎 investigation topic per `notify --topic` event.
- Buttons: `--button` repeatable, one per row; `' | '` splits buttons inside a row. `T=URL` = link, `T=cb:PREFIX:DATA` (≤ 64 bytes) = callback handled by config `callbacks` (`setup.md`). Work with `--keep` too (kept on every edit). `--keep` text ≤ 4096 visible chars (HTML tags/entities not counted).
