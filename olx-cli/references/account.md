# Account (login, msg)

## Setup

- Needs `playwright-cli` (`npm install -g @playwright/cli`) and Google Chrome. No keys: the user signs in once in the browser window; the profile keeps the login.
- Browser: the CLI starts a plain Chrome (`--user-data-dir=~/.claude/olx/browser/profiles/<session> --remote-debugging-port=<port>`) and attaches playwright-cli to it over CDP. Never a Playwright-launched or headless browser (bot walls), never a profile copied from another machine. Chrome output: `~/.claude/olx/browser/chrome.log`.
- Config (`~/.claude/olx/config.json`, every key optional):
  - `browser_session` (env `OLX_BROWSER_SESSION`): session name = profile dir (default `olx`). New name = new profile = sign in again.
  - `browser_port` (env `OLX_BROWSER_PORT`): Chrome debug port, default `9335`. Whatever Chrome answers there gets driven: keep it for this skill.
  - `browser_chrome`: Chrome executable when not on the usual path.
  - `browser_display`: X display on Linux when the env has none, e.g. an always-on Xvfb `":99"`.
  - `browser_view_url` (env `OLX_VIEW_URL`): the user's remote view of that display (noVNC link). Exit-5 texts carry it.
  - `browser_launch_prefix`: argv before the Chrome command, placeholders `{ts}` `{display}` `{path}` `{cwd}`.
- Headless Linux host: install `xdotool` (`apt install xdotool`). Sessions share one Xvfb display with no window manager, so another session's browser can bury this one; before every exit 5 the CLI raises its own window (`xdotool windowraise`). Missing xdotool → a `# ` stderr note, the command still works.
- Headless Linux host run by a bot (`claude -p` per message kills the process tree): start Chrome in its own unit:
  `["systemd-run", "--user", "--unit=olx-browser-{ts}", "--setenv=DISPLAY={display}", "--setenv=PATH={path}", "--working-directory={cwd}"]`. The CLI sets `XDG_RUNTIME_DIR` when missing. Stop: `systemctl --user stop 'olx-browser-*'`.
- Desktop (Mac): no config needed; the headed window opens on screen.
- One action at a time per session: two parallel `olx msg` calls drive the same tab.

## How it works (live 2026-11-15 olx.pt; the EU sites share one frontend)

- Signed-in check = `/myaccount/answers/` stays on www (conversation list) instead of redirecting to `login.olx.<tld>`. The redirect is client-side, after load.
- `msg send` / `msg list --id`: listing id/URL → offer API (url, seller name, `contact.chat`; chat off → exit 2 before the browser) → ad page → its own "Enviar mensagem" button (`data-testid=ad-contact-message-button`). OLX routes to the existing conversation `/myaccount/answer/<cid>/` or a new one `/myaccount/answer/new/?ad_id=…&user_uuid=…`, so a second message lands in the same thread.
- Composer: `textarea[name="message.text"]` + the form's `button[type=submit]` (shown once there is text); max 5000 chars.
- Bubbles: `data-testid=sent-message | received-message` (aria-label names the sender), text `[data-testid=message]`, `[data-testid=message-status-label]` = time, or a sending / undelivered / read note. Sent = a new own bubble with the text whose label shows a digit (time).
- Inbox rows: `data-testid=conversations-list-item-<cid>`; name, ad title, snippet, date testids `list-item-*`. A status icon before the snippet = own last message (`last_by=me`); bold = unread.
- Selectors were read from olx.pt's chat bundles while signed out; the signed-in pages were not seen yet. Thread order assumed oldest first. A wrong row → read the dump / ARIA, fix `src/api/js/prelude.js`, add a `// live <date>` note.
- An image-only last message from the other side shows an attachment icon: `last_by` may say `me`. `msg list --conversation CID` to check.

## Failures

- Exit 5 "captcha": not seen yet; the user solves it in the window. Space out calls; don't loop.
- Exit 1 leaves `~/.claude/olx/dumps/<step>-<ts>.png` + `.txt` (URL, title, ARIA snapshot). Read them before retrying.
- `could not attach` / `Chrome did not open its debug port`: another Chrome on the port, or no display (`browser_display`). `chrome.log` has Chrome's side.
