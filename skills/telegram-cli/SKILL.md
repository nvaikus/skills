---
name: telegram-cli
description: Reads, searches and sends Telegram messages as the user's own Telegram account (MTProto via Telethon, not a bot) - search across all chats or inside one chat, public channel post search, find people/groups/channels by name or @username, chat history, send a message or a file. Several accounts per machine. Use when a task needs something from the user's Telegram - "find in Telegram", "what did X write", "search the chats for", "who is @x", "message X in Telegram", "send a file to X", "send to the group", "tg-cli". NOT for building Telegram bots or the Bot API.
---

# telegram-cli

```
tg-cli [--account NAME] <command> ...     # python3 ~/.claude/skills/telegram-cli/tg-cli.py
tg-cli chats [FILTER] | user-find <q>     # who/where: ids for everything below
tg-cli search <words> [--chat C] [--from U] [--since 7d] | search --public <words|#tag>
tg-cli history <chat> [-n N]
tg-cli send <to> [text|-] [--file PATH]...   # text = caption with --file
```

Windows: `python %USERPROFILE%\.claude\skills\telegram-cli\tg-cli.py ...`. The surface is `tg-cli --help` / `tg-cli <cmd> -h` - grep it, don't guess flags.

## Contract

- stdout TSV (`-j` JSON, `--fields a,b`, `--no-header`); stderr `# ` notes. Narrow before it reaches context: `--fields`, `-n`, `| head`.
- Exit: `0` ok · `1` Telegram failure (FLOOD_WAIT: wait, never loop) · `2` usage / not logged in / not found / ambiguous · `3` refused, nothing sent · `4` needs Premium.
- `send` sends immediately. Unsure who the target is → `chats`/`user-find` first, then send by `id` or `@username`. Exit 2 with candidates = several matches; pick one, never retry with the same name.
- Not set up yet (exit 2 naming Telethon, API keys or login) → walk the user through `references/setup.md` step by step. The agent may run `deps`; `keys` and `login` are interactive — the user runs them in a real terminal (`!` in Claude Code has no tty).

| when | read |
|---|---|
| first run, exit 2 about Telethon / API keys / login, adding an account | `references/setup.md` |

## Memory

`~/.claude/tg-cli/memory.md`: local lessons, outside the skill (updates keep it). Read first; create on first write. Cost a question, retry or context → one imperative line now; why only if it prevents a mistake. Situational → `memory/<topic>.md` behind a `<trigger> → file` line. Every-user fact → skill defect (unsure → note; proven → move it in).

- Typical entries: account names and what each is for, ids of chats the user asks about often, people's @usernames.

## Fix on friction

Gap, confusing/flooding/noisy output, stale text = skill defect; no silent workarounds. Small → fix now. Large → background `opus` teammate, one-message ticket (fact, proving command, output) fixing the faulty layer: SKILL.md, references/, scripts/, tool. Continue only if unblocked. Tracked (`skilltap status`) → edit its clone, pull, push; else in place.

- Code changes: read `src/CLAUDE.md` first; `python3 -m unittest discover -s dev/tests` must stay green.

> Source: https://github.com/nvaikus/skills/blob/main/skills/telegram-cli/SKILL.md
> Install via skilltap for auto-updates: https://github.com/nvaikus/skills/blob/main/skills/skilltap/SKILL.md
