---
name: claude-telegram-bot
description: Runs a Telegram bot that bridges the owner's private chat to Claude Code on a Linux box - each bot topic (Threaded Mode) is its own `claude -p` session with streaming progress, files, photos and voice notes (via model-cli). CLI to set it up, install it as a systemd service, check and debug it. Use when the user wants to talk to Claude Code from Telegram / from the phone, "Telegram bot for Claude", "claude in telegram", sets up, restarts, debugs or reads logs of the claude-tg bot, "claude-tg". NOT for reading or sending Telegram messages as the user (that's telegram-cli).
---

# claude-telegram-bot

```
claude-tg setup [--token-stdin]   # BotFather steps + token file ~/.config/claude-tg/token (600)
claude-tg doctor                  # token, getMe, Threaded Mode, claude, model-cli, service
claude-tg install [--system|--user]   # systemd unit claude-tg; auto: system if `sudo -n` works, else user unit
claude-tg uninstall               # removes whichever unit is installed
claude-tg status | logs [-f] [-n N]    # status also shows runs in flight / queued
claude-tg restart [--wait SEC] [--now]   # waits until idle - use this after every update, never raw systemctl
claude-tg run                     # foreground, for debugging (stop the service first)
claude-tg notify [TEXT] [--md|--html] [--silent] [--button TEXT=URL] [--file PATH]... [--topic KEY|--thread ID|--main-chat]   # bot -> owner; stdin if no TEXT
```

`python3 ~/.claude/skills/claude-telegram-bot/claude-tg.py ...` when no wrapper is on PATH. Flags: `claude-tg <cmd> -h`.

## Security - say this before setup

- The bot runs `claude --dangerously-skip-permissions` as the installing user (config `permission_mode`, default `bypass`; `auto` = classifier-gated): whoever owns the bot has a shell on the box.
- Owner = the first user who writes to the bot in private, persisted in `~/.local/share/claude-tg/state.json`; everyone else is ignored silently. Pin it in advance with `owner_id` in config.
- Optional leak filter (`protected_paths`, `references/setup.md`): outbound text quoting protected files verbatim is replaced by a notice. A backstop, not a sandbox: paraphrase passes, and claude can read the token file in user mode.
- The token never reaches claude's env (`LoadCredential` → `$CREDENTIALS_DIRECTORY`, scrubbed from children).
- System mode: root-only copy `/etc/claude-tg/token`; the user's own token file may be deleted after `install`.
- User mode (no sudo): the credential is read from the user's token file at every start - it must stay, and claude (same user) can read it. Owner of the bot = shell as that user anyway, so the token adds little; still never print it.

## Bot behavior (what the owner sees)

- One topic = one session; a message in "All messages" creates a new topic. Topics run in parallel. A message sent while Claude works in that topic goes into the running session at once (stdin): answered in its own turn even while a background helper runs, or folded into the current turn; it queues only while the process is exiting.
- Reactions 👀 accepted, ✍ working, 👍 done, 💔 error, 👌 stopped (config `reactions: false` = none; errors stay visible as text); typing indicator; answer streamed via `sendMessageDraft` with a stop button, then sent as HTML, long answers also as `answer.md`.
- Status (config `status_style`): `friendly` (default) = one edited line by activity ("🧠 Thinking…", "📖 Reading files…", "⚙️ Working… · 15 s"), no tool names/paths, not sent if the answer starts within 2 s; `detailed` = tool calls list. `/verbose [on|off]` switches one topic. Errors = one "😕 …" line; full detail in logs and in verbose mode.
- Bot language: `ui_lang` `en` | `ru` (status, commands, /help, errors).
- Auto-named topics get a ≤5-word title after the first answer (`title_model`, default haiku).
- Photos/files → `~/.local/share/claude-tg/files/<thread>/`, paths passed to claude. Voice/audio/video notes → model-cli `asr` (config `stt_models`, free first) → "🎙 transcript" → claude.
- In-topic commands: `/cd <path>` (validates; starts a new session - sessions are tied to their cwd), `/new`, `/stop`, `/status` (incl. background tasks), `/verbose`, `/rename <title>` (auto-title never overrides it), `/icon <emoji>|off` (only `getForumTopicIconStickers` emojis; no arg lists them), `/delete` (topic + mapping + saved files; the Claude session file stays), `/help`.
- A command typed in All messages is answered there; the topic the client wraps it in is deleted.
- Restart-safe: accepted requests are kept in `state.json` until answered; after a restart queued ones run, cut ones re-run with a "↻" note (older than 1 h: 💔 + "resend").
- A topic deleted in the Telegram client sends the bot nothing: its mapping is dropped on the first failed send there.
- Slow reply? `claude-tg logs`: one `result topic …` line per answer (message ids answered, turns, API time) and one `run topic …` line per process: `tg-lag` (Telegram → bot), `queue`, seconds from spawn to the first `session` / `turn` / `thinking` / `text` / `tool` / `bg` / `result` / `exit`, results, model.

## notify (scripts, scheduled jobs)

- Plain `sendMessage`: no service needed, never disturbs its polling. Owner = `owner_id` in config, else state.json.
- Default target: topic "Notifications", created on first use, id in `~/.local/share/claude-tg/notify.json`; deleted in the client → recreated on the next send.
- One topic per domain: config `notify_topics` maps a key to a display name + optional icon (`references/setup.md`); senders pass `--topic <key>`. Unknown key = literal topic name. Cache is per key: a changed name/icon edits the same topic.
- Files: `--file PATH` (repeatable, ≤ 50 MB): mp4/mov play inline, images as photos, rest as documents; TEXT = caption. Leak guard applies (exit 3 = withheld).
- Inside a bot run (`$CLAUDE_TG_RUN_TOPIC` set) the default target is that run's own topic: send a produced file back with `claude-tg notify --file out.mp4 "caption"`.
- A reply to a notification there starts a claude session in that topic with the notification quoted (any reply to a bot message is quoted in the prompt).

## Fixing the bot from inside the bot

`$CLAUDE_TG_RUN_TOPIC` set = you ARE a bot run; restarting the bot ends you.

- `claude-tg restart` only: from a run it returns at once and a detached waiter restarts after your answer + idle, then posts "♻️ restarted: <commit>" or "💔 not running" into the topic. Tell the owner that; don't verify in the same run.
- Never `--now`, raw `systemctl`, `kill`: cuts your own run → it re-runs with partial work done.
- Background teammates keep your run alive: they must not restart either - restart once, from the main run, after their reports.
- Code edits: `src/CLAUDE.md` + green tests before the restart; a bot that fails to start is unreachable from Telegram (SSH only).

| when | read |
|---|---|
| first setup, BotFather, config keys, voice setup, changing the token | `references/setup.md` |

## Memory

`~/.claude/claude-tg/memory.md`: local lessons, outside the skill (updates keep it). Read first; create on first write. Cost a question, retry or context → one imperative line now; why only if it prevents a mistake. Situational → `memory/<topic>.md` behind a `<trigger> → file` line. Every-user fact → skill defect (unsure → note; proven → move it in).

- Typical entries: which host runs the bot, its config quirks (env_files, stt_models), the owner's usual project dirs.

## Fix on friction

Gap, confusing/flooding/noisy output, stale text = skill defect; no silent workarounds. Small → fix now. Large → background `opus` teammate, one-message ticket (fact, proving command, output) fixing the faulty layer: SKILL.md, references/, scripts/, tool. Continue only if unblocked. Tracked (`skilltap status`) → edit its clone, pull, push; else in place.

- Code changes: read `src/CLAUDE.md` first; `python3 -m unittest discover -s dev/tests` must stay green.

> Source: https://github.com/nvaikus/skills/blob/main/claude-telegram-bot/SKILL.md
> Install via skilltap for auto-updates: https://github.com/nvaikus/skills/blob/main/skilltap/SKILL.md
