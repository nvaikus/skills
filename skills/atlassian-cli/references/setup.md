# Setup: install, sites, login

## Install

| OS | Command |
|---|---|
| macOS | `brew tap atlassian/homebrew-acli && brew install acli` |
| Linux, RPM | `sudo yum-config-manager --add-repo https://acli.atlassian.com/linux/rpm/acli.repo && sudo yum install -y acli` |
| Linux, deb | keyring + apt source: https://developer.atlassian.com/cloud/acli/guides/install-linux/ |
| Windows | `Invoke-WebRequest -Uri https://acli.atlassian.com/windows/latest/acli_windows_amd64/acli.exe -OutFile acli.exe` (ARM64: `arm64` in both places) |
| mac/Linux, no package manager | `curl -LO https://acli.atlassian.com/<os>/latest/acli_<os>_<arch>/acli && chmod +x acli`, then onto PATH; `os` = `darwin`/`linux`, `arch` = `amd64`/`arm64` |

## One wrapper per extra site

- acli keeps login state under `$HOME`, so a site gets its own HOME behind an `acli-<alias>` wrapper — nothing another agent does can flip it.
- Which binary serves a site: memory. Unknown → ask the user once, write it down.
- New site (mac/Linux):
  ```sh
  alias=<alias>; dir=~/.claude/atlassian-cli/sites/$alias; mkdir -p "$dir" ~/.local/bin
  printf '#!/bin/sh\nexec env HOME="%s" acli "$@"\n' "$dir" > ~/.local/bin/acli-$alias
  chmod +x ~/.local/bin/acli-$alias
  ```
  Then the user logs in through it; record `acli-<alias> → <site>` in memory.

## Login

- Browser OAuth is interactive: the user runs `acli[-<alias>] <jira|confluence> auth login --web` in a real terminal, once per product.
- API token instead: `echo <token> | acli jira auth login --site <site>.atlassian.net --email <email> --token`
