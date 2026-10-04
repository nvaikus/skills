# tg-cli setup

First run = three steps; walk the user through them one at a time, in their language.

| step | who | what |
|---|---|---|
| 1 | agent | `tg-cli deps` — venv `~/.tg-cli/venv` with Telethon + qrcode. Debian without `ensurepip` → `sudo apt install python3-venv`. No `tg-cli` on PATH → `ln -sf ~/.claude/skills/telegram-cli/tg-cli.py ~/.local/bin/tg-cli` |
| 2 | user | register the app (below), then `tg-cli keys` in a terminal |
| 3 | user | `tg-cli login` in a terminal, scan the QR; then the agent checks `tg-cli whoami` |

Terminal = a separate window, or a new tmux window (`Ctrl-b c`, back with `Ctrl-b n`). `!` in Claude Code is not a terminal: no tty, and anything typed lands in the transcript.

## Register the app (my.telegram.org)

1. Open my.telegram.org in a browser; VPN and adblock off.
2. Phone number in international form; the code arrives as a Telegram message (from "Telegram"), not SMS.
3. API development tools → form: App title `tg-cli`, Short name `tgcli` (5–32 latin letters/digits), URL empty, Platform Desktop, Description empty → Create application.
4. The page shows `App api_id` (number) and `App api_hash` (32 chars) — the only two values needed; they stay on that page.
5. Submit answers just "ERROR" → VPN/adblock/other browser; fresh accounts sometimes need to retry an hour later.

One app per Telegram account. Keys identify the program, not the person — but give everyone their own: a key abused by one user gets banned for everyone on it. Never commit keys or paste them into a chat.

## Keys: where they live

- `tg-cli keys` → `~/.tg-cli.json`, chmod 600 (default).
- Or env `TG_CLI_API_ID` / `TG_CLI_API_HASH` (override the file). macOS Keychain variant, in `~/.zshrc`:
  `export TG_CLI_API_ID="$(security find-generic-password -a "$USER" -s TG_CLI_API_ID -w 2>/dev/null)"` (same for HASH; store with `security add-generic-password -a "$USER" -s TG_CLI_API_ID -w`).

## Login and accounts

- `tg-cli login`: QR → phone: Telegram → Settings → Devices → Link Desktop Device. `--phone +…` instead: code arrives in the Telegram app. 2FA cloud password is asked after either. QR refreshes every 30 s, gives up after 3 min.
- Several accounts: `tg-cli --account work login`; `default_account` in config picks the one used without `--account`; `tg-cli accounts` lists them.
- Session = `~/.tg-cli/sessions/<account>.session`, chmod 600, full account access, lives until `tg-cli logout` or termination in Settings → Devices. One session per machine; the same file on two machines at once can get it revoked. Exit 2 "no longer authorized" → terminated from the phone; log in again.
- Machine admins (root/sudo) can read every user's session — separate OS users isolate accounts from each other, not from the admin.

## Ban risk

Reads and ordinary sends are fine. Telegram restricts accounts for mass messages to strangers, fast bursts of requests, and brand-new accounts that start messaging at once.
