# Setup: install, contexts, credentials

## Install

| OS | Command |
|---|---|
| macOS / Linux, Homebrew | `brew install gcx` |
| macOS / Linux, script | `curl -fsSL https://raw.githubusercontent.com/grafana/gcx/main/scripts/install.sh \| sh` (→ `~/.local/bin`; system-wide: `GCX_INSTALL_DIR=/usr/local/bin` + `sudo sh`) |
| Any, archive | https://github.com/grafana/gcx/releases/latest → `gcx_<ver>_<os>_<arch>.tar.gz`, verify against `gcx_<ver>_checksums.txt`, put `gcx` on PATH |

- Upgrade = same command; version unchanged → a second `gcx` earlier on PATH (`which -a gcx`).
- `grafanactl` is deprecated (repo archived); commands map 1:1 by replacing the name.
- Telemetry off: `DO_NOT_TRACK=1`.

## Credentials

- Token kind: self-hosted → a service-account token (`glsa_...`, Grafana UI: Administration → Service accounts; Viewer role for read-only work). Cloud → `--oauth`.
- Never paste a token into chat, argv history or a config file by hand; the user runs the login or stores it per their secrets rule.
- Desktop (macOS Keychain / Windows Credential Manager / Linux Secret Service): the user runs once `gcx login <ctx> --server <url> --token <glsa_...>` (or `--oauth`); gcx keeps the token in the OS store, the YAML holds only a reference.
- Headless Linux has no Secret Service: `gcx login` fails with "Keychain unavailable" and does not fall back. Use a credential-less context + token from env:
  ```sh
  gcx config set stacks.<ctx>.grafana.server https://grafana.example
  gcx config set stacks.<ctx>.grafana.org-id 1
  gcx config set contexts.<ctx>.stack <ctx>
  # token: export GRAFANA_TOKEN in the user's secrets env file (mode 600), never in config.yaml
  GRAFANA_TOKEN="$GRAFANA_TOKEN_<CTX>" gcx --context <ctx> dashboards list
  ```
  Several instances → one env var per instance + a tiny wrapper per context in `~/.local/bin`:
  `#!/bin/sh` + `GRAFANA_TOKEN="$GRAFANA_TOKEN_<CTX>" exec gcx --context <ctx> "$@"`.
- Alternative there: `GCX_KEYCHAIN=off` stores the token plaintext in the mode-600 YAML. Only if the user accepts that.
- Env-only (no config at all) needs `GRAFANA_SERVER` + `GRAFANA_TOKEN` (or `GRAFANA_USER`/`GRAFANA_PASSWORD`) + `GRAFANA_ORG_ID` (self-hosted) or `GRAFANA_STACK_ID` (Cloud); without the org id → "missing stacks.default.grafana.org-id", without any context → "Failed to find path ( $.stacks.default.grafana )".

## Check

`gcx config check`, then `gcx --context <ctx> api /api/health` and `gcx --context <ctx> datasources list`.
