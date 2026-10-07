# claude-tg setup

| step | who | what |
|---|---|---|
| 1 | user | @BotFather → `/newbot` → copy the token |
| 2 | user | @BotFather → Open (Mini App) → the bot → Bot Settings → Threads Settings → Threaded Mode on, allow users to create topics |
| 3 | user | `claude-tg setup` in a real terminal (hidden prompt). Agent-safe variant: user puts the token in a file himself, or `pbpaste \| claude-tg setup --token-stdin`. Never paste the token into the chat or argv |
| 4 | agent | `claude-tg doctor` → all ok (`threaded_mode FAIL` = step 2 not done) |
| 5 | agent | `claude-tg install` → `claude-tg logs` shows `bot @… up; topics enabled: True`. Mode is automatic (below) |
| 6 | user | writes to the bot first → becomes owner (`owner set: user id …` in logs) |

- `claude` must be logged in as the installing user (`claude` once interactively).
- Install mode: `sudo -n true` works → system unit `/etc/systemd/system/claude-tg.service` (`User=`, root token copy, no linger needed); else → user unit `~/.config/systemd/user/claude-tg.service` (`systemctl --user`, no sudo). An existing unit keeps its mode; force with `--system` / `--user`. Other commands follow the installed unit file.
- User mode needs linger, or the bot dies at logout: `doctor` row `linger FAIL` → the admin runs `sudo loginctl enable-linger <user>` (one time).
- User mode logs: `journalctl --user -u claude-tg` - own user journal, no `adm` group needed (persistent journal, uid ≥ 1000).
- Token changed → `claude-tg setup`, then `claude-tg install` again (system mode: refreshes `/etc/claude-tg/token`; user mode: just restarts).
- One poller per token: `run` refuses while the service holds the lock; a second host with the same token shows `409` in logs.
- macOS: no service support (launchd out of scope); `claude-tg run` inside tmux works.

## Config `~/.config/claude-tg/config.json` (optional, all keys optional)

| key | default | meaning |
|---|---|---|
| `token_file` | `~/.config/claude-tg/token` | where `setup` writes and `install` copies from |
| `owner_id` | null | pin the owner (Telegram user id) instead of first-come |
| `default_cwd` | `~` | cwd of new topics |
| `claude_bin` | PATH, then `~/.local/bin/claude` | claude executable |
| `claude_args` | `[]` | extra args for every run, e.g. `["--model", "opus"]` |
| `title_model` | `haiku` | model for topic titles |
| `env_files` | `[]` | `KEY=VALUE` files loaded into the bot and claude env - the service does not source shell rc files, so API keys (e.g. model-cli's `HF_TOKEN`, `OPENROUTER_API_KEY`) go here |
| `stt_models` | `[""]` | model-cli asr models tried in order; `""` = model-cli's default (HF whisper) |
| `claudeai_connectors` | true | false = `ENABLE_CLAUDEAI_MCP_SERVERS=false` for claude: no claude.ai account connectors (Gmail, Drive…), so unauthenticated ones stop showing up in answers |
| `ui_lang` | `en` | bot-facing language: `en` \| `ru` |
| `status_style` | `friendly` | `friendly` = one short activity line; `detailed` = tool calls + thinking (debug). Per topic: `/verbose` |
| `reactions` | true | false = no status reactions (👀 ✍ 👍 💔 👌) on the owner's messages; typing, status line, draft and error text stay |
| `stt_paid` | false | allow paid STT (`--paid`); e.g. add `openrouter:google/gemini-2.5-flash-lite` (fractions of a cent per note) |
| `permission_mode` | `bypass` | `bypass` = `--dangerously-skip-permissions`; `auto` \| `default` \| `acceptEdits` → `--permission-mode <v>`. `auto` = classifier-gated tools, works headless on Sonnet/Opus; Haiku silently falls back to `default` (`doctor` WARN). A denied call → one "🚫 not allowed" line per tool per turn, logged; claude goes on |
| `protected_paths` | `[]` | leak filter: dirs/files/globs (`~`, `$VAR` expanded) whose text must never go out verbatim. Any answer, draft, status, notify text or file quoting ≥ `protect_min_words` consecutive words of them → replaced by a "hidden" notice, logged as `leak blocked topic … quotes <file>`; files under these paths are never sent. Paraphrase passes. Index rebuilt on change (checked at run start); `doctor` shows its size. An unlistable dir (`--x`) indexes nothing: list its readable files explicitly |
| `protect_min_words` | 12 | words in a row that count as a quote (words = letters/digits, case and markup ignored) |
| `local_api_url` | null | local Bot API server for attachments > 20 MB (section below) |
| `local_api_id` / `local_api_hash` | `rbw:TELEGRAM_API_ID` / `rbw:TELEGRAM_API_HASH` | secret references for that server |
| `local_api_bin` | PATH, then `~/.local/bin/telegram-bot-api` | server binary |
| `notify_topics` | `{}` | `notify --topic KEY` registry: `{"mail": {"name": "Mail", "icon": "📝"}, "ci": "CI"}`. `icon` = an emoji from `getForumTopicIconStickers` (fixed set, e.g. 💬 💻 🤖 📣 📝 🔥 ❗) or its custom_emoji_id; anything else → no icon, warning. Keep emoji out of `name`: the client shows the icon beside it. Editing name/icon renames the cached topic on the next send (no new topic). Key `Notifications` = the default topic |
| `protect_exempt_marker` | `.user-made` | a dir holding this file is not protected (the user's own skills) |

Restart after edits or skill updates: `claude-tg restart` (waits until no run is active).

## Files over 20 MB (optional local Bot API server)

- Cloud Bot API downloads ≤ 20 MB. Bigger attachment, no local server: skipped. The owner gets what/why/workaround; claude gets a note (name, type, size, message id, reason). The rest of the message still runs.
- A local `telegram-bot-api --local` (unit `claude-tg-botapi`, `systemctl --user`) raises the limit to 2 GB. Downloads only: polling and sending stay on the cloud, no `logOut`. A stopped server only affects big files (owner sees "server does not respond").

| step | who | what |
|---|---|---|
| 1 | user | api_id + api_hash: my.telegram.org → API development tools (an existing app such as tg-cli's works). Into the secret store, never chat: `rbw add --folder env TELEGRAM_API_ID`, then `... TELEGRAM_API_HASH` (value = first line in the editor) |
| 2 | agent | build: `sudo apt-get install -y make git zlib1g-dev libssl-dev gperf cmake g++`; `git clone --recursive https://github.com/tdlib/telegram-bot-api`; in it `mkdir build && cd build && cmake -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX:PATH=$HOME/.local .. && cmake --build . --target install -j4` → `~/.local/bin/telegram-bot-api` (15-30 min, ~1 GB RAM per job; one binary per host, any user may point `local_api_bin` at it) |
| 3 | agent | config `"local_api_url": "http://127.0.0.1:8081"` (one free port per bot on the host) |
| 4 | agent | `claude-tg local-api install` → `claude-tg local-api status` ok → `claude-tg restart` |

- Secrets: `local_api_id` / `local_api_hash` are references, resolved by `local-api serve` at start and passed to the binary via env: `rbw:NAME` (default `rbw:TELEGRAM_API_ID` / `rbw:TELEGRAM_API_HASH`), `env:NAME` (process env or `env_files`), `cred:NAME` (systemd credential: `$CREDENTIALS_DIRECTORY/NAME`, else `~/.config/credstore.encrypted/NAME` decrypted with `systemd-creds decrypt --user` - the user manager of systemd < 258 can't `LoadCredentialEncrypted=`). A literal value is refused.
- Several bots on one host, one admin's app: per bot user `rbw get NAME | sudo -u <user> systemd-creds encrypt --user --name=NAME - ~<user>/.config/credstore.encrypted/NAME` (value never on screen or in a plain file), config `cred:NAME`; binary in a path every bot user can execute (`/usr/local/bin`); one port each.
- Locked vault (after reboot or `lock_timeout`) → the server can't start, the unit retries every 60 s: the owner runs `rbw unlock`.
- Server files: `~/.local/share/claude-tg/botapi/` (700); each download is copied to the topic's files dir and removed there.

## Voice

- Needs the model-cli skill + a token for its backend in `env_files`. Missing → the bot answers with an install hint.
- Default = HF whisper on the free $0.10/month credit; once it is spent (HTTP 402) voice fails until the monthly reset.
- No working free ASR on OpenRouter (the free omni model ignores the audio and answers anything). Reliable paid fallback: `"stt_models": ["", "openrouter:google/gemini-2.5-flash-lite"], "stt_paid": true` - owner's decision, it costs money.
- Audio is converted to 16 kHz mono mp3 with ffmpeg first (chat-audio models reject ogg/opus). Each model gets 2 tries.
