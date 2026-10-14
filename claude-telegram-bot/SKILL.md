---
name: claude-telegram-bot
description: Runs a Telegram bot that bridges the owner's private chat (or a forum supergroup shared by a few allowed users) to Claude Code on a Linux box - each bot topic (Threaded Mode) is its own `claude -p` session with streaming progress, files, photos and voice notes (via model-cli). CLI to set it up, install it as a systemd service, check and debug it. Use when the user wants to talk to Claude Code from Telegram / from the phone, sets up, restarts, debugs or reads logs of the claude-tg bot. NOT for reading or sending Telegram messages as the user (that's telegram-cli). Triggers - Telegram bot for Claude, claude in telegram, claude-tg.
---

# claude-telegram-bot

```
claude-tg setup [--token-stdin]   # BotFather steps + token file ~/.config/claude-tg/token (600)
claude-tg doctor                  # token, getMe, Threaded Mode (group mode: group, admin rights, allowed_users), claude, model-cli, service
claude-tg chats                   # group setup: group ids + sender ids from pending updates (service stopped)
claude-tg install [--system|--user]   # systemd unit claude-tg; auto: system if `sudo -n` works, else user unit
claude-tg uninstall               # removes whichever unit is installed
claude-tg status | logs [-f] [-n N]    # status also shows runs in flight / queued
claude-tg restart [--wait SEC] [--now]   # waits until idle - use this after every update, never raw systemctl
claude-tg run                     # foreground, for debugging (stop the service first)
claude-tg notify [TEXT] [--md|--html] [--silent] [--button TEXT=URL] [--file PATH]... [--topic KEY|--thread ID|LINK|--main-chat] [--chat NAME] [--replace KEY] [--keep KEY [--pin]] [--topic-icon E]   # bot -> owner; stdin if no TEXT
claude-tg notify-delete [KEY]... [--id MSG]...   # delete what --replace KEY last sent (exit 1 = some not deleted)
claude-tg spawn --title T [--cwd DIR] [--icon E] [--start-icon E] [--system TEXT|@FILE] [--silent] [--show TEXT] [--quiet] [--chat NAME] [PROMPT]   # new topic + session; stdin if no PROMPT
claude-tg send --thread ID|LINK [--silent] [--show TEXT] [--quiet] [PROMPT]   # prompt into a topic as the owner (live run: stdin; else resume)
claude-tg alive --thread ID|LINK   # exit 0 = run live or queued there, 1 = idle
claude-tg topic-icon --thread ID|LINK <emoji|off|base>   # base = icon from /icon or spawn --icon
claude-tg profile [--name T] [--description T] [--short T] [--photo FILE|--photo-remove] [--lang CODE]   # bot's own name / empty-chat text / about / avatar; no flags = show
claude-tg local-api install|status|uninstall   # optional local Bot API server: attachments up to 2 GB (setup.md)
```

`python3 ~/.claude/skills/claude-telegram-bot/claude-tg.py ...` when no wrapper is on PATH. Flags: `claude-tg <cmd> -h`.

## Security - say this before setup

- The bot runs `claude --dangerously-skip-permissions` as the installing user (config `permission_mode`, default `bypass`; `auto` = classifier-gated): whoever owns the bot has a shell on the box.
- Owner = the first user who writes to the bot in private, persisted in `~/.local/share/claude-tg/state.json`; everyone else is ignored silently. Pin it in advance with `owner_id` in config.
- Optional leak filter (`protected_paths`, `references/setup.md`): outbound text quoting protected files verbatim is replaced by a notice. A backstop, not a sandbox: paraphrase passes, and claude can read the token file in user mode.
- The token never reaches claude's env (`LoadCredential` → `$CREDENTIALS_DIRECTORY`, scrubbed from children).
- System mode: root-only copy `/etc/claude-tg/token`; the user's own token file may be deleted after `install`.
- User mode (no sudo): the credential is read from the user's token file at every start - it must stay, and claude (same user) can read it. Owner of the bot = shell as that user anyway, so the token adds little; still never print it.

## Group mode (several people, one bot)

- When: a project bot that 2+ people drive, every topic visible to all. Config `group_id` (forum supergroup, `-100…`) + `allowed_users` (user ids); absent = private-owner mode as above. Setup: `references/setup.md` (Group mode).
- Only `allowed_users` in that group are heard (empty list = nobody); everyone/everything else is ignored silently (one log line per source per hour). All allowed users are equal (commands, ⏹); `owner_id` is unused. The bot leaves any other group it is added to.
- Topics, notify, spawn/send, restart reports all go to the group. Each prompt line is tagged `[From: Name (@user, id N)]`. Links: `https://t.me/c/<group id without -100>/<thread>/2147483647`.
- General topic of any group (this and owner groups) is ignored by default: messages and commands (`/start` too), no reply, no new topic, one log line per chat per hour. Work happens in topics. Config `group_general: true` = heard again (a message there opens a topic). Outbound (`notify` without a topic) still posts there. The private chat is unaffected.
- Telegram allows ~20 messages/min per group: status updates are slower than in private, answers stream by message edits (no drafts).

## Owner groups (private mode + extra forum groups)

- When: one owner, topics of a project kept in their own forum group. Config `owner_groups`: `{"name": -100…}` (private mode only; ignored with `group_id`). Setup: `references/setup.md` (Owner groups).
- In those groups only the owner is heard; anyone else, bots, anonymous admins are ignored. Every topic is its own session, like in the private chat. A group not in `owner_groups`: the bot stays if the owner added it (logs its id), else leaves.
- `spawn` / `send` / `alive` / `topic-icon` / `notify` / `notify-delete` take `--chat NAME|ID`; default = the private chat. A `t.me/c/<chat>/<thread>` link carries its chat, so `--thread LINK` needs no `--chat`. Runs get `CLAUDE_TG_RUN_CHAT` next to `CLAUDE_TG_RUN_TOPIC`: `notify` and `restart` reports from inside a run go back to its own chat.
- Group limits apply there (no drafts, ~20 msg/min).

## Addressing people (every mode)

- Telegram notifies only on a mention. Every run gets an addressing rule appended to its system prompt: the people (group: `allowed_users` via getChatMember; private: the owner via getChat; a day in `cache.json`) with their mention (`@username`, else a `[Name](tg://user?id=N)` text mention) and names + config `people_aliases`.
- Group: whoever a message asks for something is addressed only by mention, never "Name:". Any mode: a final message that waits on a person starts with the mention(s) + the ask - one message, no separate ping; a tracked task also records the wait (`github-tasks needs --who`).
- Safety net: an answer line opening with a known name as a header (`Name:`, `**Name:**`) is rewritten to the mention (not in code fences).

## Bot behavior (what the owner sees)

- One topic = one session; a message in "All messages" creates a new topic. Topics run in parallel. A message sent while Claude works in that topic goes into the running session at once (stdin): answered in its own turn even while a background helper runs, or folded into the current turn; it queues only while the process is exiting.
- Reactions off by default; config `reactions: true` turns on 👀 accepted, ✍ working, 👍 done, 💔 error, 👌 stopped (errors stay visible as text either way); typing indicator (at turn start, then only while no status/draft is on screen); answer streamed via `sendMessageDraft` with a stop button, then sent as HTML, long answers also as `answer.md`.
- Status (config `status_style`): `friendly` (default) = one edited line by activity ("🧠 Thinking…", "📖 Reading files…", "⚙️ Working… · 15 s"; timer in 15 s / 30 s / 1 min steps, timer-only edits ≥ 10 s apart), no tool names/paths, not sent if the answer starts within 2 s; `detailed` = tool calls list, at most one edit per 6 s. `/verbose [on|off]` switches one topic. `/quiet [on|off]` (or `spawn/send --quiet`): text blocks between tool calls go into the status message (top line, edited, deleted with it) instead of separate messages; only the final answer stays - it must be self-contained. Errors = one "😕 …" line; full detail in logs and in verbose mode. Status edits, drafts and typing share a per-chat budget (Telegram limits are per chat across topics): with many parallel topics they update less often; after a 429 they pause until the flood wait ends while answers and error lines wait and are still delivered (log: `flood wait N s` / `flood wait over`). The flood state lives in `STATE_DIR/flood.json`, shared with CLI calls (`notify`, `spawn`, `send`, `topic-icon`): during a wait `topic-icon` is skipped (stderr note, `"skipped": true`), sends wait.
- Bot language: `ui_lang` `en` | `ru` (status, commands, /help, errors).
- Auto-named topics get a ≤5-word title after the first answer (`title_model`, default haiku).
- Photos/files → `~/.local/share/claude-tg/files/<thread>/`, paths passed to claude. Over 20 MB: needs the local Bot API server (`local_api_url`), else skipped: owner gets why + workaround, claude a note; rest of the message runs. Voice/audio/video notes → model-cli `asr` (config `stt_models`, free first) → "🎙 transcript" → claude.
- In-topic commands: `/cd <path>` (validates; starts a new session - sessions are tied to their cwd), `/new`, `/stop`, `/status` (incl. background tasks), `/verbose`, `/quiet`, `/rename <title>` (auto-title never overrides it), `/icon <emoji>|off` (only `getForumTopicIconStickers` emojis; no arg lists them), `/delete` (topic + mapping + saved files; the Claude session file stays), `/help`.
- A command typed in All messages is answered there; the topic the client wraps it in is deleted.
- Restart-safe: accepted requests are kept in `state.json` until answered; after a restart queued ones run, cut ones re-run with a "↻" note (older than 1 h: 💔 + "resend").
- A topic deleted in the Telegram client sends the bot nothing: its mapping is dropped on the first failed send there.
- Slow reply? `claude-tg logs`: one `result topic …` line per answer (message ids answered, turns, API time) and one `run topic …` line per process: `tg-lag` (Telegram → bot), `queue`, seconds from spawn to the first `session` / `turn` / `thinking` / `text` / `tool` / `bg` / `result` / `exit`, results, model.

## notify (scripts, scheduled jobs)

- Plain `sendMessage`: no service needed, never disturbs its polling. Owner = `owner_id` in config, else state.json.
- Default target: topic "Notifications", created on first use, id in `~/.local/share/claude-tg/notify.json`; deleted in the client → recreated on the next send.
- One topic per domain: config `notify_topics` maps a key to a display name + optional icon (`references/setup.md`); senders pass `--topic <key>`. Unknown key = literal topic name. Cache is per key: a changed name/icon edits the same topic.
- Files: `--file PATH` (repeatable, ≤ 50 MB): mp4/mov play inline, images as photos, rest as documents; TEXT = caption. Leak guard applies (exit 3 = withheld).
- One live status message (a board): `--keep KEY [--pin]` edits the message stored for (chat, KEY) in place (`edited` / `unchanged` in the output, no new message, no sound); none yet or deleted → a new one, pinned with `--pin` (bot needs `can_pin_messages` in a group). One message: text ≤ 4096. `--topic-icon E` sets the `--topic` topic's icon without a `notify_topics` entry. Bot API cannot pin a topic in the topic list.
- Recurring post (digest, status) that must not pile up: `--replace KEY` sends, then deletes the messages last sent under KEY (ids in notify.json `replace`). Delete failure (bots can't delete > 48 h old in some chats, already gone) = stderr warning, exit stays 0. `notify-delete KEY` removes it without a new post.
- Inside a bot run (`$CLAUDE_TG_RUN_TOPIC` set) the default target is that run's own topic: send a produced file back with `claude-tg notify --file out.mp4 "caption"`.
- A reply to a notification there starts a claude session in that topic with the notification quoted (any reply to a bot message is quoted in the prompt).

## spawn / send (scripts driving sessions)

- Need the running service: the prompt is posted into the topic as a bot message (the owner sees it; `--show TEXT` posts that short human line instead, claude still gets the full prompt), queued in `~/.local/share/claude-tg/inbox/`, run by the bot like an owner message. Bot down = waits there.
- `spawn` prints `{thread, link, message_id, cwd}` (+ `chat` in an owner group, link `t.me/c/...`); `link` = `https://t.me/<bot>/<thread>/2147483647` (int32-max message id → opens the topic at its last message; `/<thread>` alone opens only the creation message in the main chat). Old `/<thread>` and `/<thread>/<msg>` links still parse as `--thread`. `--system` = per-topic role appended to claude's system prompt on every run of that topic. `--quiet` = the topic becomes quiet (`/quiet`), kept for later runs. `--icon` = base icon (kept, `topic-icon base` restores it); `--start-icon` = created with that icon instead, not kept (a status mark like ❗ that can't be skipped for rate budget, unlike a later `topic-icon`); output gets `icon` when one was set.
- `alive` = a process with `CLAUDE_TG_RUN_TOPIC=<thread>`, a pending request or an inbox file. A finished turn ends the process: idle between turns is normal.
- Status-only lines into a topic (no claude turn): `notify --thread ID --silent`.

## Fixing the bot from inside the bot

`$CLAUDE_TG_RUN_TOPIC` set = you ARE a bot run; restarting the bot ends you.

- `claude-tg restart` only: from a run it returns at once and a detached waiter restarts after your answer + idle, then posts "♻️ restarted: <commit>" or "💔 not running" into the topic. Tell the owner that; don't verify in the same run.
- Never `--now`, raw `systemctl`, `kill`: cuts your own run → it re-runs with partial work done.
- Background teammates keep your run alive: they must not restart either - restart once, from the main run, after their reports.
- Owner asks to change the bot's name / about / description / avatar → `claude-tg profile ...` (no restart). A photo they sent is a file path in your prompt → `--photo <path>`.
- Code edits: `src/CLAUDE.md` + green tests before the restart; a bot that fails to start is unreachable from Telegram (SSH only).

| when | read |
|---|---|
| first setup, BotFather, config keys, group mode setup, voice setup, changing the token, files over 20 MB / local Bot API server | `references/setup.md` |

## Memory

`~/.claude/claude-tg/memory.md`: local lessons, outside the skill (updates keep it). Read first; create on first write. Cost a question, retry or context → one imperative line now; why only if it prevents a mistake. Situational → `memory/<topic>.md` behind a `<trigger> → file` line. Every-user fact → skill defect (unsure → note; proven → move it in).

- Typical entries: which host runs the bot, its config quirks (env_files, stt_models), the owner's usual project dirs.

## Fix on friction

Gap, confusing/flooding/noisy output, stale text = skill defect; no silent workarounds. Small → fix now. Large → background `opus` teammate, one-message ticket (fact, proving command, output) fixing the faulty layer: SKILL.md, references/, scripts/, tool. Continue only if unblocked. Tracked (`skilltap status`) → edit its clone, pull, push; else in place.

- Code changes: read `src/CLAUDE.md` first; `python3 -m unittest discover -s dev/tests` must stay green.

> Source: https://github.com/nvaikus/skills/blob/main/claude-telegram-bot/SKILL.md
> Install via skilltap for auto-updates: https://github.com/nvaikus/skills/blob/main/skilltap/SKILL.md
