---
name: whatsapp-cli
description: Reads, searches and sends WhatsApp messages as the user's own WhatsApp account (a linked device over the multi-device protocol via neonize/whatsmeow, not the Business API) - chat history, full-text search over a local store, download media (documents, photos, voice...), find people and chats by name or phone, send a message or a file, inspect or join a group by invite link, read a channel's posts without following it. Several accounts per machine. Use when a task needs something from the user's WhatsApp - "find in WhatsApp", "what did X write in WhatsApp", "search WhatsApp for", "message X on WhatsApp", "send a file to X on WhatsApp", "what is this chat.whatsapp.com link", "read this WhatsApp channel", "download the PDF / photo from WhatsApp", "wa-cli". NOT for WhatsApp bots or the Cloud/Business API.
---

# whatsapp-cli

```
wa-cli [--account NAME] <command> ...      # python3 ~/.claude/skills/whatsapp-cli/wa-cli.py
wa-cli chats [FILTER] | user-find <q>      # who/where: jids and names for everything below
wa-cli search <words> [--chat C] [--from U] [--since 7d]
wa-cli history <chat> [-n N] [--ids ID,ID]
wa-cli download <chat> <msg_id>...|all [-o DIR] [--kind document,image] [--since/--until]  # media -> files
wa-cli send <to> [text|-] [--file PATH]...    # text = caption of the first file
wa-cli group-info <invite-link> | channel-info <link> | channel-fetch <channel> [-n N]
```

Windows: `python %USERPROFILE%\.claude\skills\whatsapp-cli\wa-cli.py ...`. The surface is `wa-cli --help` / `wa-cli <cmd> -h` - grep it, don't guess flags.

## Contract

- stdout TSV (`-j` JSON, `--fields a,b`, `--no-header`); stderr `# ` notes. Narrow before it reaches context: `--fields`, `-n`, `| head`.
- Exit: `0` ok · `1` WhatsApp failure (rate limit / ban: stop, never retry in a loop) · `2` usage / not logged in / not found / ambiguous · `3` refused, nothing sent.
- Reads come from a local store: every command connects, pulls what arrived, then answers (a few seconds); `<cmd> ... --offline` (per-command flag, not global) skips the connect. Only messages that reached this device exist - since `login` plus the phone's initial history sync. No server search, no older history.
- `send` sends immediately. Unsure who the target is → `chats`/`user-find` first, then send by jid or +phone. Exit 2 with candidates = several matches; pick one, never retry with the same name.
- Ban hygiene - WhatsApp bans accounts for automation patterns: one-off sends only, one recipient per call, only on the user's request; never loop `send` over a list, never `join` more than the one group the user asked for. Exit 1 about a rate limit or ban → stop and tell the user.
- `download` saves media by `msg_id` (from `history`/`search`; media rows read `[document] name.pdf`). Status `no-keys` = stored before wa-cli kept media keys (2026-10-06): only a new history sync (logout + login, the user's call) brings them. `expired` = gone from WhatsApp's servers; wa-cli cannot ask the phone to re-upload - the user saves it from the phone.
- Extra `-j`/`--fields` keys: messages `out`, `reply_to_msg_id`, `reply_to_me` (quoted sender is my phone jid or lid, or the quoted message is mine), `mentions_me`, `my_reaction` (own reaction emoji or null; reactions stored since 2026-10-09 + the history sync); chats `members` (groups, from the hourly groups refresh; `sync` forces it). `reply_to_me`/`mentions_me` = null on messages stored before 2026-10-09. No muted/archived: neonize delivers no Mute/Archive app-state events.
- No channel directory search (WhatsApp's "Find channels" is not in whatsmeow): get the channel link from the user or the web.
- Channels: `channel-fetch` reads posts without following (verified live 2026-10-04); `channel-info` `following` yes/no is the only follow signal. `chats` hides unfollowed channels (`--all` shows them); their posts stay searchable.
- Not set up yet (exit 2 naming neonize, libmagic or login) → walk the user through `references/setup.md` step by step. The agent may run `deps`; `login` is interactive - the user runs it in a real terminal (`!` in Claude Code has no tty).

| when | read |
|---|---|
| first run, exit 2 about neonize / libmagic / login, adding an account, "logged out" | `references/setup.md` |

## Memory

`~/.claude/wa-cli/memory.md`: local lessons, outside the skill (updates keep it). Read first; create on first write. Cost a question, retry or context → one imperative line now; why only if it prevents a mistake. Situational → `memory/<topic>.md` behind a `<trigger> → file` line. Every-user fact → skill defect (unsure → note; proven → move it in).

- Typical entries: account names and what each is for, jids of chats the user asks about often, channel links.

## Fix on friction

Gap, confusing/flooding/noisy output, stale text = skill defect; no silent workarounds. Small → fix now. Large → background `opus` teammate, one-message ticket (fact, proving command, output) fixing the faulty layer: SKILL.md, references/, scripts/, tool. Continue only if unblocked. Tracked (`skilltap status`) → edit its clone, pull, push; else in place.

- Code changes: read `src/CLAUDE.md` first; `python3 -m unittest discover -s dev/tests` must stay green.

> Source: https://github.com/nvaikus/skills/blob/main/whatsapp-cli/SKILL.md
> Install via skilltap for auto-updates: https://github.com/nvaikus/skills/blob/main/skilltap/SKILL.md
