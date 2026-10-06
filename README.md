# skills

Claude Code skills, installable one at a time.

Every skill is a top-level folder `<name>/`: `SKILL.md`, plus for CLI skills the CLI (`<cli>.py`), `src/`, `dev/tests/`, `references/`.

## Skills

| Skill | What it does |
|---|---|
| [model-cli](model-cli/SKILL.md) | Find, call and fetch results from non-Claude models (image, video, TTS, ASR, LLM) via Hugging Face, OpenRouter and Pollinations, free tiers first |
| [telegram-cli](telegram-cli/SKILL.md) | Search, read and send Telegram messages as your own account (MTProto via Telethon): search across chats, find people and channels, send |
| [whatsapp-cli](whatsapp-cli/SKILL.md) | Search, read and send WhatsApp messages as your own account (linked device via neonize/whatsmeow): local full-text store, media download, group invite links, channel posts |
| [gmail-cli](gmail-cli/SKILL.md) | Gmail for agents: search all accounts with Gmail query syntax, threads as compact markdown, labels and bulk organizing, drafts, replies and send |
| [icloud-calendar-cli](icloud-calendar-cli/SKILL.md) | iCloud Calendar over CalDAV from any OS: calendars with kind and access (own, shared, subscribed), events in a range with recurrences expanded, add, edit, delete |
| [ebay-cli](ebay-cli/SKILL.md) | Buyer-side eBay search via the official Browse API: listings with shipping priced for your country, item cards, category ids, saved searches reporting new listings and price drops |
| [google-drive-cli](google-drive-cli/SKILL.md) | Google Drive as a local filesystem (rclone mount / synced folder) plus Google Docs and Sheets by path: read Docs as markdown, targeted edits, Sheets as TSV |
| [clockmaster-cli](clockmaster-cli/SKILL.md) | Run jobs on a schedule through the OS's own scheduler (launchd, systemd user timers, Task Scheduler): run history, logs, notifications, claude cost, local web UI; migrates the old task-scheduler |
| [skilltap](skilltap/SKILL.md) | Install single skills from any git repo and keep them updated on session start; admin-managed skill list; publish skill edits back through the source clone |
| [claude-telegram-bot](claude-telegram-bot/SKILL.md) | Telegram bot bridge to Claude Code: one bot topic = one `claude -p` session, streaming progress, files and voice; systemd install, doctor, logs |
| [survive-compaction](survive-compaction/SKILL.md) | Hooks that make long sessions survive auto-compaction: context-size orders to keep a progress doc (main session and subagents), a re-read order after compaction, archived summaries; bash + jq, tested |
| [agent-messaging](agent-messaging/SKILL.md) | Direct SendMessage between agents of one session: addressing, delivery at turn boundaries, waiting, reporting to the lead, briefing a team |
| [step-by-step](step-by-step/SKILL.md) | One-decision-at-a-time planning cadence: short proposals, a yes before the next, auto-exit once the plan is agreed |
| [atlassian-cli](atlassian-cli/SKILL.md) | Jira and Confluence Cloud via Atlassian's acli: help-first discovery, a markdown ⇄ ADF converter for descriptions and comments, REST recipes for attachments and custom fields, one wrapper per site |

## Install

Copy a skill folder into `~/.claude/skills/<name>/`, or install it with auto-updates via [skilltap](skilltap/SKILL.md):
`skilltap get https://github.com/nvaikus/skills/tree/main/model-cli`

Get skilltap itself (macOS / Linux; Windows: [references/how-it-works.md](skilltap/references/how-it-works.md)):

```sh
curl -fsSL https://raw.githubusercontent.com/nvaikus/skills/main/skilltap/skilltap.py | python3 - get https://github.com/nvaikus/skills/blob/main/skilltap/SKILL.md && python3 "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills/skilltap/skilltap.py" hook
```

## License

MIT — see [LICENSE](LICENSE).
