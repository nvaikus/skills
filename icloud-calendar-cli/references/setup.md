# Setup (onboarding, credentials, hosts)

## Files
- `~/.claude/icloud-calendar/<profile>/config.json` (root via `ICAL_ROOT`): Apple ID, env var NAMES, cached discovery (principal, calendar home on a `pNN-caldav.icloud.com` host, notifications URL, own addresses), `default_calendar` (id), `tz`. Never the password. `config.json` at the root: `default_profile`.
- Discovery runs once per profile; a moved account (401/404 on the cached home) → delete `principal`/`home` from the profile config and rerun.

## Credentials
- Only an app-specific password works (2FA accounts reject the normal password over CalDAV). Revoking it at account.apple.com or changing the Apple ID password invalidates it → 401 → onboarding step `password-rejected`.
- Read order: env var named by `password_env` (default `ICLOUD_APP_PASSWORD`) → `password_cmd` (shell command printing it; `onboard --password-cmd 'CMD'`). Apple ID: env `ICLOUD_APPLE_ID` → config `apple_id`.
- A new export is invisible to the running Claude: the user must restart it.
- Second Apple ID: `onboard --profile NAME --password-env ICLOUD_APP_PASSWORD_NAME` so the two passwords live in different variables.

## Other machines
- Linux desktop: `secret-tool` (libsecret) + export in the shell rc; onboarding prints the commands.
- Headless server without a keyring: set the env var for the one command from the machine that holds it (`ssh host "ICLOUD_APP_PASSWORD=... icloud-calendar list"` sends it over the encrypted channel but leaves it in the remote process env), or `password_cmd` reading a root-only file / a secret manager. Never paste it into chat.
- Credentials are sent only to `https://*.icloud.com`; subscribed feeds are fetched without them.
