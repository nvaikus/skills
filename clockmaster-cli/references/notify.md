# Notifications

- Gate per task, `notify:`: `failure` (default: failed/timeout/killed), `on` (every run), `off`. Applied once for every channel. Best effort: never changes a run's status; silent failures leave a line in `<data>/notify.log` (trimmed past 256 KB).
- Message: title = task, body = `✅ success in 1m 04s` (❌ failed, ⏱️ timeout, 💀 killed, ⏹️ stopped).

## Desktop

| OS | how | sound |
|---|---|---|
| macOS | `<data>/notifier.app`, built on demand, bundle `com.claude.clockmaster-notifier` | `sound:` name from /System/Library/Sounds (Basso Blow Bottle Frog Funk Glass Hero Morse Ping Pop Purr Sosumi Submarine Tink, case-sensitive); default Blow; `off` |
| Linux | `notify-send` when a display exists, else no-op + notify.log line | desktop default |
| Windows | WinRT toast via PowerShell | `off` = silent; a name plays the default sound |

macOS:
- First banner asks permission for "clockmaster" (System Settings > Notifications). Denied = silent no-op. Bundle id and bytes are stable, so the grant survives updates; only a new icon or launcher costs one re-grant. A greyed duplicate in that list is an old bundle.
- Focus modes and the per-app "Play sound" switch can mute it: not a broken key.
- Click opens that run in the web UI (starts the UI if down). No payload exists: with stacked banners ANY click opens the latest run; a click older than 2 min opens the UI root.
- Without a compiler the bundle uses a copy of osascript: banners still post, clicks do nothing.

## Teams channel

`<data>/notify.yaml`, user-local:

```yaml
teams_team: <team / group id>
teams_channel: 19:...@thread.tacv2
# teams: off              # pause, keep the ids
# m365_cli: ~/path/to/m365-cli.py   # default: the installed m365-cli skill
```

- No file, `teams: off` or a missing id = no post, silently. Needs the m365-cli skill signed in. Ids only: a name costs a throttled Graph lookup.
- Subject `<task> — ✅ success in 1m 04s`; body = output.log (last 20 000 chars, with an "omitted" line) in a code block + muted `exit · trigger · run` line.
- Failed post → notify.log line (m365-cli exit 4 = Graph throttled).

## Telegram

`<data>/notify.yaml`, user-local; needs the claude-telegram-bot skill set up (its bot writes to the owner):

```yaml
telegram: on
# telegram_topic: system      # claude-tg notify_topics key or literal name; default: its default topic
# claude_tg: ~/.local/bin/claude-tg   # default: on PATH, else ~/.local/bin/claude-tg (services have a bare PATH)
```

- Text = `<task> — ❌ failed in 1m 04s`, the last 1500 chars of output.log in a code block, `exit · trigger · run` line.
- Failed send → notify.log line.

## Adding a channel

`src/notify/<name>.py` with `send(msg)`, name added to `CHANNELS` in `src/notify/__init__.py`; config keys in notify.yaml.
