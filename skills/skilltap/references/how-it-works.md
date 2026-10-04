# How skilltap works

## Bootstrap (new machine)

macOS / Linux:

```sh
curl -fsSL https://raw.githubusercontent.com/nvaikus/skills/main/skills/skilltap/skilltap.py | python3 - get https://github.com/nvaikus/skills/blob/main/skills/skilltap/SKILL.md && python3 "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills/skilltap/skilltap.py" hook
```

Windows (PowerShell):

```powershell
iwr https://raw.githubusercontent.com/nvaikus/skills/main/skills/skilltap/skilltap.py -OutFile $env:TEMP\skilltap.py; python $env:TEMP\skilltap.py get https://github.com/nvaikus/skills/blob/main/skills/skilltap/SKILL.md; python "$env:USERPROFILE\.claude\skills\skilltap\skilltap.py" hook
```

Installs skilltap as a skill tracked from this repo (so it updates itself), adds the SessionStart hook to `settings.json`, writes a `skilltap` wrapper to `~/.local/bin`.

## Layout (under `$CLAUDE_CONFIG_DIR` or `~/.claude`)

| Path | Holds |
|---|---|
| `skilltap/sources/<host-owner-repo>/` | one git clone per repo |
| `skilltap/lock.json` | tracked skills: name → repo, path, origin, content hash |
| `skilltap/backups/` | edits found in installed copies before a refresh overwrote them |
| `skills/<name>/` | the installed copy Claude Code reads |

## Mechanics

- Skill name = `name:` in `SKILL.md`, else the folder name; `--name` overrides.
- Refresh = `git pull --rebase --autostash` per clone (never commits or pushes), then rebuilds only skills whose content changed. New copy is built outside `skills/` and swapped in by rename; a locked folder (Windows) keeps the old copy, swap retried next time.
- Never mirrored: `.git`, `__pycache__`, `*.pyc`, `.DS_Store`.
- Git calls time out (`SKILLTAP_GIT_TIMEOUT`, default 60 s; clone ×5) and never prompt.
- Parallel sessions share a lock; a hook run that finds it busy skips.
- Upstream history rewritten (repo recreated) and rebase fails → a clone with no local work is reset to the new upstream; one with local work stops with an error.
- `get --force` on a tracked name switches its source; the old clone is deleted once no skill uses it and it holds no unpushed work.

## Moves (repo renames a skill or its folder)

A source repo declares moves in `skilltap-moves.json` at its root:

```json
{ "moves": [ { "from": "clis/gdrive", "to": "skills/google-drive-cli", "from_name": "gdrive", "to_name": "google-drive-cli" } ] }
```

- Read from the local clone on every `refresh` (even when fresh) and `apply`; chains are followed; a move wins even if the old path still exists.
- Tracking `from` → path switches to `to`. Installed as `from_name` (and `to_name` free) → folder renamed; a custom `--name` keeps its name.
- Old install dir / clone path is repointed in: `~/.local/bin` (text + symlinks), `<root>/settings.json` + `settings.local.json`, `~/.config/systemd/user` (daemon-reload, try-restart), `~/Library/LaunchAgents` (reload if loaded), crontab. `/etc/systemd/system` units need root: warned, fix by hand.
- `SKILLTAP_NO_SERVICE_CMDS=1` → files repointed, service commands only printed (tests).
- Admin lists may name old or new paths/names; they are translated, no flip-flop.
- Repo side: append-only; keep entries while old installs may exist. Moving skilltap itself needs a symlink at its old path until every old client has updated once (old clients skip missing paths).

## Admin list

```json
{ "skills": { "some-skill": { "repo": "https://github.com/owner/repo.git", "path": "skills/some-skill" } } }
```

`skilltap apply list.json` installs what is missing (origin `list:<path>`), switches the source of its own skills when the list changes it, and removes what it installed and the list no longer names. `user` skills and untracked folders are never touched; a user skill with the same repo+path stays the user's. `skilltap hook` wires `<root>/baseline/skills.json` into the SessionStart hook when that file exists.

## Coming from skillsync

`skilltap migrate-from-skillsync` re-tracks everything in `<root>/skillsync/manifest.json` (reusing its clones), swaps the old SessionStart hook for skilltap's, deletes the old tool.
