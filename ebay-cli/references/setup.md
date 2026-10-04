# Setup facts (keys, machines, files)

## Keys
- Lookup order: env `EBAY_CLIENT_ID` / `EBAY_CLIENT_SECRET` > macOS Keychain generic password with service = that name, account = `$USER` (read live, no shell restart) > `~/.claude/ebay/credentials.json` (chmod 600, written by `setup --keys-stdin`). `doctor` names the source, masked.
- Only App ID (Client ID) + Cert ID (Client Secret) of the **Production** keyset. Dev ID is unused. Sandbox keys mint tokens on another host and are refused here (`invalid_client`).
- New production keysets stay disabled until the Marketplace Account Deletion step is done (opt-out "Not persisting eBay data"); until then the token call answers `invalid_client`.
- Rotated keys: store the new ones the same way; the cached token is keyed by App ID and re-minted.
- Application token only (client credentials, scope `api_scope`): no user login, no access to the user's own eBay account.

## Machines and files
- `~/.claude/ebay/`: `config.json` (market, ship_to, zip, setup progress), `token.json` (~2 h token), `credentials.json` (if used), `watch/`. Survives skill updates. `EBAY_ROOT` relocates it.
- Env overrides per run: `EBAY_MARKET`, `EBAY_SHIP_TO`, `EBAY_ZIP` (never persisted).
- Another machine: same keys work anywhere; store them there (Keychain / env / `--keys-stdin`), copy `watch/` to keep saved searches and their seen state.
- Headless Linux under cron: env vars or `credentials.json`; the Keychain is macOS only.
