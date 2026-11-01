# `claude-tg notify` internals

Read when touching `notify.py`. User-facing behavior: `../../references/notify.md`.

- Owner chat, topic registry (`notify_topics` key → name/icon), thread id + applied name/icon cached per key (`notify.json`, not state.json - the bot owns that).
- Sticker list (7 d, unknown emoji refetches hourly) + bot username (30 d) in `cache.json`.
- `cli_bot` = shared flood state + stderr wait note.
- `--file` uploads (video/photo/document, fallback document). 2+ photos/videos → `_album`: `sendMediaGroup` via `Bot.upload_many` (`attach://fN`), `album_chunks` splits evenly into 2..10 (never a lone item: Telegram rejects 1); a 400 → one by one. Caption fit = `visible_len` ≤ 1024.
- Default target = `$CLAUDE_TG_RUN_TOPIC` inside a run.
- `--replace KEY` / `notify-delete`: ids per key in `notify.json` `replace`, send before delete, 400 delete = forget, transient = keep for retry.
- `--keep KEY`: `notify.json` `keep["<chat>:<key>"]` = {thread, message_id}, editMessageText in place, `not modified` = unchanged, other 400 = gone → resend (+ pin).
- `keyboard(buttons)`: each `--button` = a row, `' | '` splits; `button()` = url or `cb:` → callback_data (prefix + `:` required, ≤ 64 bytes). `keep` passes reply_markup on edit and send. `chunks(html)` measures `visible_len` (tags stripped, entities unescaped, UTF-16).
- Callback clicks: `Bridge.button` (auth as ⏹) → `callback_cmd` (built-in `CALLBACKS` + config `callbacks`, `shutil.which`) → thread `callback`: run `argv DATA --chat <name>` (CALLBACK_TIMEOUT), edit message with its JSON, answer the query after (toast on error, `not modified` ignored).
