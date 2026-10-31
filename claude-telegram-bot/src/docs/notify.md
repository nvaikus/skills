# `claude-tg notify` internals

Read when touching `notify.py`. User-facing behavior: `../../references/notify.md`.

- Owner chat, topic registry (`notify_topics` key → name/icon), thread id + applied name/icon cached per key (`notify.json`, not state.json - the bot owns that).
- Sticker list (7 d, unknown emoji refetches hourly) + bot username (30 d) in `cache.json`.
- `cli_bot` = shared flood state + stderr wait note.
- `--file` uploads (video/photo/document, fallback document).
- Default target = `$CLAUDE_TG_RUN_TOPIC` inside a run.
- `--replace KEY` / `notify-delete`: ids per key in `notify.json` `replace`, send before delete, 400 delete = forget, transient = keep for retry.
- `--keep KEY`: `notify.json` `keep["<chat>:<key>"]` = {thread, message_id}, editMessageText in place, `not modified` = unchanged, other 400 = gone → resend (+ pin).
