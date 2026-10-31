# claude-tg — developer brief

Keep this file one screen. Entry `claude-tg.py` → `src/main.py:main`.

## Invariants — never break

- Python 3.9+, stdlib only (raw Bot API over urllib; no aiogram). Threads, not asyncio: one poller thread, one worker thread per topic (+ a short inject thread per message sent mid-run: prompt building - downloads, STT - never runs on the poller/timer thread).
- The token lives only in `botapi.Bot` and `config.read_token`. Never log URLs; `main.TokenFilter` redacts it from log lines as a backstop. `runner.ChildEnv` keeps it only to scrub; `runner.child_env` drops `CREDENTIALS_DIRECTORY`, `CLAUDE_TG_*` and any var containing the token. The unit file never contains it (`LoadCredential`: system mode from a root-only copy, user mode from the user's token file).
- Every send into a topic passes `message_thread_id` (without it a reply lands in "All messages").
- Cosmetic calls (typing, status edits, drafts, reactions) go through `Bridge.quiet` / `_retries=0`: a 429 there must never block reading claude's stdout.
- Telegram limits are per chat, shared by all topics; one 429 bans the whole chat. Every call goes through `botapi.Flood` (per Bot, per chat): cosmetic calls skip during a flood wait, real sends wait and retry; details in `docs/transport.md`.
- Runtime state only under `~/.local/share/claude-tg/` and config under `~/.config/claude-tg/`; nothing inside the skill dir.

## Area docs — read when

| when | read |
|---|---|
| `runner.py`, `streamjson.py`, run/turn logic of `Worker` (stdin turns, resume, hooks, interim posts) | `docs/claude-process.md` |
| topics, drafts, status message / ticker, ⏹ button, burst debounce, `ui.S` strings, bot profile photo | `docs/telegram-ux.md` |
| `botapi.py` (`Flood`, `fast_connect`), big files / `localapi.py`, 429s, silences, 409 | `docs/transport.md` |
| `state.json` / pending / `restore()`, `restart` / `install`, `inbox.py` (`spawn` / `send`) | `docs/state.md` |
| owner groups, peer bots, group mode / General, addressing people in answers | `docs/groups.md` |
| `notify.py` (`--replace`, `--keep`, topic registry, caches) | `docs/notify.md` |

## Layers

| file | owns |
|---|---|
| `main.py` | argv, logging, single-instance lock |
| `config.py` | paths, config defaults, token + env-file reading |
| `botapi.py` | HTTP, multipart upload, file download, `TgError` |
| `bridge.py` | update routing, owner lock, commands, `Worker` (queue, run, UX, rename), `Status` (status message ticker) |
| `general.py` | General mention detection (UTF-16 entity offsets), ring buffer per chat, context block |
| `ui.py` | every bot-facing string (`S[lang][key]`, en + ru, same keys), tool → phase, status line |
| `runner.py` | claude argv, env scrub, process group kill, one-shot titles |
| `streamjson.py` / `fmt.py` | pure parsers: stream-json → events; markdown → Telegram HTML + splitter |
| `media.py` | attachment download (cloud ≤ 20 MB, local server above, `Skipped`), model-cli STT |
| `localapi.py` | `claude-tg local-api`: user unit `claude-tg-botapi`, `serve` resolves secret refs (env/cred) into env and execs the server, probe for doctor |
| `guard.py` | leak filter: sorted N-word window hashes of `protected_paths`, `match` / `file_leak`; `Bridge.leak`, `Worker.answer` / `_stream` (one notice per turn, tripped block stops streaming), detailed `Status`, `fail`, `notify` |
| `notify.py` | `claude-tg notify`: owner chat, topic registry, `--file`, `--replace` / `--keep`, caches in `notify.json` / `cache.json` (`docs/notify.md`) |
| `triage.py` | `claude-tg triage` (writes only config `notify_triage`) + `after_notify`: gating (`skip`), `inbox.spawn` of a "🔎" topic, dedupe by `signature` in `STATE_DIR/triage.json` under flock, button via `editMessageReplyMarkup`; never raises into notify |
| `inbox.py` | `spawn` / `send` / `alive` / `topic-icon`: inbox files (CLI side) + `apply` (bot side), liveness from `/proc` env + pending + inbox |
| `groups.py` | `claude-tg group list/add/remove`: rewrites only config `owner_groups` (atomic, mode kept; tenants can't touch the config path), chat id from the bot's journal (`service.journal`), getChat/getChatMember checks, `service.restart` |
| `peerbots.py` | `claude-tg bots list/add/remove`: rewrites only config `allowed_bots` (`groups.write_key`); `@name` → id from `ignored: bot ID (@name)` journal lines |
| `botprofile.py` | `claude-tg profile`: getMy*/setMy* name, descriptions, profile photo |
| `service.py` | systemd unit (system / user mode: user unit file present → user), doctor, setup |

## Test

- `python3 -m unittest discover -s dev/tests` — offline, pure modules.
- Live: `claude-tg doctor`; end-to-end = message the bot from the owner account (tg-cli can do it), check the reply lands in the same topic.
