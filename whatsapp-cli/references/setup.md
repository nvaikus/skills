# wa-cli setup

First run = two steps; walk the user through them one at a time, in their language.

| step | who | what |
|---|---|---|
| 1 | agent | `wa-cli deps` — venv `~/.wa-cli/venv` with neonize (whatsmeow as a bundled native lib). Needs Python 3.10+ and the system libmagic: macOS `brew install libmagic`, Debian `sudo apt install libmagic1 python3-venv`. No `wa-cli` on PATH → `ln -sf ~/.claude/skills/whatsapp-cli/wa-cli.py ~/.local/bin/wa-cli` |
| 2 | user | `wa-cli login` in a terminal, link the device; then the agent checks `wa-cli whoami` |

Terminal = a separate window, or a new tmux window (`Ctrl-b c`, back with `Ctrl-b n`). `!` in Claude Code is not a terminal: no tty.

## Login

- QR (default): phone → WhatsApp → Settings → Linked devices → Link a device → scan. The QR refreshes itself; gives up after 3 min.
- `--phone +351…` instead: an 8-character code is printed; on that phone: Link a device → "Link with phone number instead" → type it.
- After linking it waits up to 3 min while the phone sends recent history. Keep the phone online and WhatsApp open. That sync is the only history wa-cli will ever have (WhatsApp sends a recent window, not everything).
- The device shows on the phone as "wa-cli (Chrome)". The phone must come online at least every ~14 days or WhatsApp unlinks all devices → exit 2 "logged out" → `wa-cli logout`, `wa-cli login`.
- Several accounts: `wa-cli --account work login`; `default_account` in `~/.wa-cli.json` picks the one used without `--account`; `wa-cli accounts` lists them.

## Files

- `~/.wa-cli/accounts/<name>/session.db` — whatsmeow's device keys = full account access (chmod 600). One machine per session: copying it elsewhere makes both kick each other off.
- `~/.wa-cli/accounts/<name>/store.db` — wa-cli's message store (SQLite + FTS5, chmod 600). `logout --purge` deletes it.
- `~/.wa-cli/logs/<name>.log` — neonize/whatsmeow log (warnings and errors).
- Only one wa-cli runs per account at a time; a second waits up to 20 s, then exit 1 "busy".
- Machine admins (root/sudo) can read every user's files — separate OS users isolate accounts from each other, not from the admin.

## Ban risk

Unofficial clients are against WhatsApp's terms; accounts get banned for automation patterns, not for being linked. Reads and occasional one-off sends are low risk. High risk: messages to many people or strangers, bursts of sends, joining many groups, a brand-new number that starts messaging at once. A temporary ban (exit 1 "TEMPORARY BAN") → stop all wa-cli use on that account until it expires; never retry in a loop.
