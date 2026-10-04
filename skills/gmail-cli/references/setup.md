# Setup facts (onboarding, login, machines)

## Layout
- `~/.claude/gmail/<profile>/`: `config.json` (client id/secret, project, account; chmod 600), `token.json` (refresh token, chmod 600), `login-pending.json` while a login runs. Root `config.json` = `default_profile` (the first finished onboarding sets it). Survives skill updates.
- Env: `GMAIL_PROFILE` (= `--profile`), `GMAIL_ROOT`, `GMAIL_DOWNLOADS` (attachment default dir, else `<tmp>/gmail`), `GMAIL_CLIENT_ID`/`GMAIL_CLIENT_SECRET` (override, never stored).
- `profiles --remove NAME` deletes only local files; the grant stays at myaccount.google.com/permissions.

## The OAuth key
- One Desktop-app client serves every account: `onboard` copies it from another gmail profile (one with a proven Gmail API first), else from `~/.claude/gdrive/<profile>/config.json` (same name, then gdrive's default). `--client-from gdrive:NAME|gmail:NAME` picks another; `--client-file` imports a downloaded JSON; `--new-client` runs the console steps (project, API, consent, branding, publish, key).
- The Gmail API is enabled per Cloud project, not per account: the first account on a key asks for it, later ones skip it. A reused gdrive key = gdrive's project; its consent screen name ("Personal Drive") is what the user sees on Google's page.
- "API enabled" can take a few minutes to reach Gmail: `onboard` returns exit 6 (`RUNNING apis-propagating`) for 5 min after `--done apis`, then asks again.

## Login
- Scope `gmail.modify` (+ openid email): read, labels, drafts, send, trash. It cannot delete permanently - by design.
- Granular consent: the Gmail box may start unticked. Unticked → `login --finish` exits 2 "left unticked"; rerun `onboard` and tick it.
- Gmail scopes are "restricted": the consent page always warns "Google hasn't verified this app" (Advanced → Go to ... (unsafe)). Expected for a personal key; Google's 100-user cap for unverified apps is irrelevant here.
- External app left in Testing: refresh token dies after 7 days; `onboard` detects it after login and walks branding + publish + a new login (same pages as gdrive, `references/setup.md` there). The account must be a Test user while in Testing.
- `invalid_grant` / 401 = token revoked or expired → `gmail onboard --profile NAME` shows the login step again.
- Another machine: copy `~/.claude/gmail/` (secrets: scp, not chat) or onboard there again (the key is reused from a gdrive profile if one exists).
