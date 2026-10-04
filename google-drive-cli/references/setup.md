# Setup facts (onboarding, login, machines)

## Layout
- `~/.claude/gdrive/<profile>/`: `config.json` (client id/secret, project, mount choice; chmod 600), `rclone.conf` (token, chmod 600), `index/`, `index.sqlite`. Root `config.json` = `default_profile`. Survives skill updates.
- Shared by profiles: `~/.local/share/gdrive/` (rclone `bin/`, mount records `mounts/`, `logs/` incl. `index-<profile>.log`). Disposable VFS cache: `~/.cache/gdrive/<profile>/<mount id>` (NOT disposable while `status` shows pending uploads).
- Rename = `profiles --rename OLD NEW`, never `mv`: it also moves the cache root (pending uploads resume after remount), the index log, rewrites mount records/units and reinstalls the index service. Exit 3 while OLD is mounted/syncing/indexing. `GDRIVE_PROFILE` and scripts naming OLD stay stale.
- v0.1 `~/.gdrive.json` + `~/.config/gdrive/rclone.conf`: imported once by `onboard` into a profile that has no client; never read again.

## Automatic mode (`--mode auto`)
- Optional path, core CLI stays stdlib: needs Node.js + Playwright (`playwright-core`, found in the global npm root incl. `@playwright/cli`'s nested copy; `GDRIVE_PLAYWRIGHT=<dir>` overrides) + Chrome/Chromium/Edge (`GDRIVE_CHROME`). Off over SSH, on Linux without DISPLAY, or `GDRIVE_AUTO=off`. Check: `node scripts/console-auto.mjs --check`.
- Chrome runs as a plain process with its own profile `<profile>/auto/browser` (never the user's main profile); Playwright attaches over CDP only after the user is on the console (Google refuses sign-in in automated browsers). Deleted when the job succeeds; left (signed in) after a failure.
- `<profile>/auto/`: `status.json` (state/step/msg/screenshot/warnings), `job.log` (driver stderr), `shots/<step>-*.png` (failure screenshots), `plan.json`.
- Branding/publish failures are not fatal: the job continues, the login is a Testing one, onboard then shows steps 6-7 by hand. Any other failure → that step's manual text; `--mode auto` retries (resumes where it stopped, reuses the open window). Sign-in wait 15 min (`GDRIVE_SIGNIN_MIN`), consent click 10 min.

## Google Cloud side
- Consent screen Audience: **Internal** exists only for Google Workspace (company) accounts - no verification, no 100-user cap, token never expires by policy. Personal gmail: **External** + **Publish app**; left in Testing, refresh tokens die after 7 days. After publishing, the user must log in once more (a Testing-era token keeps its 7-day expiry).
- `onboard` detects both after login: id_token `hd` claim = Workspace; `refresh_token_expires_in` in the token response = Testing app → it asks for branding + publish and a new login. (Live 2026-10-01: gmail Testing app returns it; after publish + re-login it is absent = permanent.)
- Publish app greyed out (live 2026-10-01) until Branding has Application home page + privacy policy link on an Authorised domain. Shared pages work for ANY user, no domain verification: home `https://nvaikus.github.io/personal-drive/`, privacy `.../privacy.html`, domain `nvaikus.github.io` (GitHub Pages, own repo outside the skills repo). Still impossible → `onboard --keep-testing` (re-login every 7 days).
- App name must be "Personal Drive": names like gdrive / G-drive are refused (Google trademark).
- Right after publishing, the consent URL may give Google "500 That's an error": wait ~2 min or use an incognito window.
- Testing app: the user must be listed under Audience → Test users, else the login is refused.
- "Google hasn't verified this app": Testing app shows Continue; published unverified app shows Advanced → Go to Personal Drive (unsafe).
- Consent screen leaves the Drive checkbox UNTICKED (granular consent): a token with only email/openid → `login --finish` exits 2 "insufficient scopes"; redo the login with the box ticked.
- The OAuth client must be **Desktop app**: a Web client JSON (`"web"` key) is refused. Loopback redirect `http://127.0.0.1:53682/` needs no registration for Desktop clients.
- APIs are enabled per project: the key file's `project_id` wins over the one typed at step 2 (mismatch = APIs re-asked for that project).
- A disabled API = exit 2 naming it; `onboard` re-probes Drive/Docs/Sheets after every login.

## Login
- Agent-driven: the browser ends on an unreachable `http://127.0.0.1:53682/?code=...`; the user pastes that address, the agent pipes it to `gdrive --profile P login --finish` within 10 min. Re-running `onboard` reuses the same URL for 9 min (a new one would invalidate the pasted code).
- `invalid_grant` on refresh = token revoked or 7-day Testing expiry → `onboard` shows step 5 again.
- Another machine: copy `~/.claude/gdrive/<profile>/config.json` + `rclone.conf`, run `gdrive onboard --profile P --where DIR` there (the stored mount dir is absolute): it installs rclone, mounts, installs services, builds the index.

## Machine
- rclone is downloaded into `~/.local/share/gdrive/bin` (SHA256-verified, no admin); a system rclone is never used.
- Linux mount needs `/dev/fuse` + `fusermount3` (package `fuse3`); without them `mount` falls back to a sync folder. macOS: nothing to install (`nfsmount`). Windows: WinFsp (`winget install WinFsp.WinFsp`), no autostart and no index service in v1.
- Autostart (mount `--persist`, index service) on Linux = systemd **user** units: they run while the user has a session; for a headless box the admin runs `loginctl enable-linger <user>`.
