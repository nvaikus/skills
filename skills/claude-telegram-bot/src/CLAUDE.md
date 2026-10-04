# claude-tg — developer brief

Keep this file one screen. Entry `claude-tg.py` → `src/main.py:main`.

## Invariants — never break

- Python 3.9+, stdlib only (raw Bot API over urllib; no aiogram). Threads, not asyncio: one poller thread, one worker thread per topic (+ a short inject thread per message sent mid-run: prompt building - downloads, STT - never runs on the poller/timer thread).
- The token lives only in `botapi.Bot` and `config.read_token`. Never log URLs; `main.TokenFilter` redacts it from log lines as a backstop. `runner.child_env` drops `CREDENTIALS_DIRECTORY`, `CLAUDE_TG_*` and any var containing the token. The unit file never contains it (`LoadCredential`: system mode from a root-only copy, user mode from the user's token file).
- Every send into a topic passes `message_thread_id` (without it a reply lands in "All messages").
- Cosmetic calls (typing, status edits, drafts, reactions) go through `Bridge.quiet` / `_retries=0`: a 429 there must never block reading claude's stdout.
- Runtime state only under `~/.local/share/claude-tg/` and config under `~/.config/claude-tg/`; nothing inside the skill dir.

## Non-obvious facts

- `claude -p` needs `--include-partial-messages` for `text_delta` events; tool calls come from full `assistant` messages. `parent_tool_use_id != null` = subagent.
- A failed `--resume` = `result` with `is_error`, `num_turns: 0`, stderr `No conversation found` → worker resets the session and reruns once. Sessions are stored per cwd, so `/cd` resets the session.
- Private-chat topics: the first message of a user-created topic carries `reply_to_message.forum_topic_created` (`is_name_implicit` → we may rename). `createForumTopic` / `editForumTopic` work in private chats.
- `sendMessageDraft`: ephemeral 30 s preview, replaced by the next real message; `can_stop` adds a stop button → `stopped_message_generation` update with `draft_id`. Any non-429 failure flips the bridge to edit-message streaming for the process lifetime.
- Thinking arrives as `content_block_start` type `thinking` + `thinking_delta`s whose text is often empty (model omits it) → show an indicator, snippets only when text exists. `message_start` = a model turn began.
- Deleting a topic in the client produces no update; send errors `message thread not found` / `TOPIC_*` → `Bridge.forget`. `Store.drop` blocks later writes so a finishing run can't resurrect it.
- Every Bot API call goes through `botapi.fast_connect`: 4 s connect timeout per address, last good family first. Plain urllib spent the whole 35/65 s timeout on a blackholed IPv6 route before IPv4 (seen as 30-40 s silences). `HTTPConnection.__init__` sets `_create_connection` per instance - override it there.
- Pending requests live in `state.json` until done; SIGTERM → `Bridge.shutdown` kills runs but keeps them; `restore()` re-runs on start. `claude-tg restart` / `install` wait for an empty `pending`. Inside a bot run (`CLAUDE_TG_RUN_TOPIC` set) `restart` would wait for itself: it detaches a waiter (`systemd-run --user`: `KillMode=control-group` would kill a plain child with the old bot) that restarts when idle and reports to the topic via `--report`.
- `Status` renders from a 0.5 s ticker thread (elapsed time moves while a tool runs silently); the event loop only sets attributes. Once shown, it is edited in place, never re-sent: a new message would wipe the `sendMessageDraft` preview.
- Forward-with-comment = comment, then each forward as separate updates < 1 s apart (albums: N updates). `Bridge.collect` debounces per topic (`BURST` 1 s, `ALBUM` 1.5 s, `FORWARD` 6 s - a forwarded photo came 5 s after its text) → one run; a burst in All messages gets one `new_topic` at flush.
- Prompts go on stdin (`--input-format stream-json`, one process, many turns: `system/init` + `result` per turn). `--replay-user-messages` echoes each line with our `uuid` when claude takes it in → `Worker.sent`/`seen` map every `result` to the batches it answers (a mid-turn line is absorbed into the running turn; a finished helper starts a turn with no line). `background_tasks_changed.tasks` = full list of running top-level tasks. `Worker.maybe_close` closes stdin when idle, 0 tasks, nothing sent unseen, nothing being built; closing is safe any time (claude finishes helpers + their turn, then exits). Failed `--resume` exits by itself.
- `result` carries only the last text block; drafts die in 30 s. An ended text block followed by more events (or 3 s of silence, e.g. waiting for a background Agent) is posted as a real message by `Worker.post_interim`; the final answer is skipped if identical to the last posted one.
- New bot-facing text → a key in both `ui.S` tables (a test checks key/placeholder parity).
- `getUpdates` 409 = another poller with the same token; the file lock in `STATE_DIR/lock` only guards one host.

## Layers

| file | owns |
|---|---|
| `main.py` | argv, logging, single-instance lock |
| `config.py` | paths, config defaults, token + env-file reading |
| `botapi.py` | HTTP, multipart upload, file download, `TgError` |
| `bridge.py` | update routing, owner lock, commands, `Worker` (queue, run, UX, rename), `Status` (status message ticker) |
| `ui.py` | every bot-facing string (`S[lang][key]`, en + ru, same keys), tool → phase, status line |
| `runner.py` | claude argv, env scrub, process group kill, one-shot titles |
| `streamjson.py` / `fmt.py` | pure parsers: stream-json → events; markdown → Telegram HTML + splitter |
| `media.py` | attachment download, model-cli STT |
| `notify.py` | `claude-tg notify`: owner chat, remembered topic (`notify.json`, not state.json - the bot owns that) |
| `service.py` | systemd unit (system / user mode: user unit file present → user), doctor, setup |

## Test

- `python3 -m unittest discover -s dev/tests` — offline, pure modules.
- Live: `claude-tg doctor`; end-to-end = message the bot from the owner account (tg-cli can do it), check the reply lands in the same topic.
