---
name: claude-telegram-bot
description: Runs a Telegram bot that bridges the owner's private chat (or a forum supergroup shared by a few allowed users) to Claude Code on a Linux box - each bot topic (Threaded Mode) is its own `claude -p` session with streaming progress, files, photos and voice notes (via model-cli). CLI to set it up, install it as a systemd service, check and debug it. Use when the user wants to talk to Claude Code from Telegram / from the phone, sets up, restarts, debugs or reads logs of the claude-tg bot, or wants to change the bot's own name, avatar / profile photo or description (the bot does it itself via `claude-tg profile`, no BotFather). NOT for reading or sending Telegram messages as the user (that's telegram-cli). Also when topics of a project, client or personal stream should live in their own forum group (owner groups). Triggers - Telegram bot for Claude, claude in telegram, claude-tg, separate group for these topics, отдельная группа для топиков, сменить аватарку / картинку / имя бота.
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
claude-tg notify [TEXT] [--md|--html] [--silent] [--button TEXT=URL] [--file PATH]... [--topic KEY|--thread ID|LINK|--main-chat] [--chat NAME] [--replace KEY] [--keep KEY [--pin]] [--topic-icon E] [--triage|--no-triage]   # bot -> owner; stdin if no TEXT
claude-tg triage [show] | on [--cwd DIR] [--chat NAME] [--cooldown MIN] [--topics KEY..|all] [--exclude KEY..|none] | off   # auto-triage of notify events
claude-tg notify-delete [KEY]... [--id MSG]...   # delete what --replace KEY last sent (exit 1 = some not deleted)
claude-tg spawn --title T [--cwd DIR] [--icon E] [--start-icon E] [--system TEXT|@FILE] [--settings ABS.json] [--silent] [--show TEXT] [--quiet] [--chat NAME] [PROMPT]   # new topic + session; stdin if no PROMPT
claude-tg send --thread ID|LINK [--silent] [--show TEXT] [--quiet] [PROMPT]   # prompt into a topic as the owner (live run: stdin; else resume)
claude-tg alive --thread ID|LINK   # exit 0 = run live or queued there, 1 = idle
claude-tg topic-icon --thread ID|LINK <emoji|off|base>   # base = icon from /icon or spawn --icon
claude-tg group list | add NAME [ID] [--no-restart] | remove NAME   # owner groups; add w/o ID = newest group the owner added the bot to
claude-tg bots list | add BOT | remove BOT [--no-restart]   # peer bots heard in groups (allowed_bots); BOT = id or @name from the logs
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

## Areas (one line each; details behind the table below)

- Group mode: one forum supergroup (`group_id`) shared by `allowed_users`, all equal, every topic visible to all.
- Peer bots: another bot in our group is heard only when it addresses us (`claude-tg bots add`); loop guard `bot_turns_max`.
- Who a group message is for: a person's message runs claude only when it is for the bot (mention, `/cmd`, reply to us, bare message right after ours).
- Bot behavior: one topic = one session, parallel topics, status line, in-topic commands, files/voice, restart-safe queue, slow-reply logs.
- notify: bot → owner from scripts/jobs (`--topic KEY`, `--keep`, `--replace`, `--file`); opt-in auto-triage opens a 🔎 topic per event.
- spawn / send: scripts open or prompt topics through the running service; `alive` checks a topic.

## Owner groups (private mode + extra forum groups)

- One owner, a project's topics in their own forum group: user creates it and makes the bot admin with Manage Topics; connect only via `claude-tg group add NAME [ID]` / `remove NAME`, never by editing the config.
- Then `spawn` / `send` / `alive` / `topic-icon` / `notify` / `notify-delete` take `--chat NAME|ID`; a `t.me/c/...` link carries its chat. Rules: `references/groups.md`.

## Addressing people (every mode)

- Telegram notifies only on a mention. Every run gets an addressing rule appended to its system prompt: the people (group: `allowed_users` via getChatMember; private: the owner via getChat; a day in `cache.json`) with their mention (`@username`, else a `[Name](tg://user?id=N)` text mention) and names + config `people_aliases`.
- Group: whoever a message asks for something is addressed only by mention, never "Name:". Any mode: a final message that waits on a person starts with the mention(s) + the ask - one message, no separate ping; a tracked task also records the wait (`github-tasks needs --who`).
- Safety net: an answer line opening with a known name as a header (`Name:`, `**Name:**`) is rewritten to the mention (not in code fences).

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
| group mode rules, owner groups, peer bots, why a group message did / didn't run claude | `references/groups.md` |
| what the owner sees: reactions, status line / `status_style`, `/quiet`, flood waits, in-topic commands, files and voice, restarts, slow replies | `references/behavior.md` |
| sending from scripts or jobs: `notify` (topics, files, `--keep`, `--replace`), auto-triage, `spawn` / `send` / `alive` | `references/notify.md` |

## Memory

`~/.claude/claude-tg/memory.md`: local lessons, outside the skill (updates keep it). Read first; create on first write. Cost a question, retry or context → one imperative line now; why only if it prevents a mistake. Situational → `memory/<topic>.md` behind a `<trigger> → file` line. Every-user fact → skill defect (unsure → note; proven → move it in).

- Typical entries: which host runs the bot, its config quirks (env_files, stt_models), the owner's usual project dirs.

## Fix on friction

Gap, confusing/flooding/noisy output, stale text = skill defect; no silent workarounds. Small → fix now. Large → background `opus` teammate, one-message ticket (fact, proving command, output) fixing the faulty layer: SKILL.md, references/, scripts/, tool. Continue only if unblocked. Tracked (`skilltap status`) → edit its clone, pull, push; else in place.

- Code changes: read `src/CLAUDE.md` first; `python3 -m unittest discover -s dev/tests` must stay green.

> Source: https://github.com/nvaikus/skills/blob/main/claude-telegram-bot/SKILL.md
> Install via skilltap for auto-updates: https://github.com/nvaikus/skills/blob/main/skilltap/SKILL.md
