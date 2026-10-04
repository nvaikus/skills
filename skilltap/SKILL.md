---
name: skilltap
description: Installs single Claude Code skills from any git repo (GitHub, GitLab, any git URL) and keeps them updated on session start; reconciles an admin-managed skill list; publishes skill edits back through the source clone. Use when the user gives a link to a skill (SKILL.md or a skill folder in a repo) and wants it installed, asks to update/refresh tracked skills, stop tracking or remove one, check which skills are outdated, or edit/improve a skill that skilltap tracks. Triggers - install this skill, add skill from github, update my skills, skill status, untrack skill, edit a tracked skill, publish skill fix, skilltap. NOT for writing a new skill from scratch (that's skill-creator).
---

# skilltap

One CLI (`skilltap`, Python stdlib) that tracks skills by `repo + path`, keeps one git clone per repo under `<root>/skilltap/sources/`, and mirrors each skill into `<root>/skills/<name>/`. `<root>` = `$CLAUDE_CONFIG_DIR` or `~/.claude`. A SessionStart hook runs `refresh` once a day.

## Invariants

- **Never edit an installed copy** (`<root>/skills/<name>/` of a tracked skill): the next refresh overwrites it (edits land in `<root>/skilltap/backups/`). Edit flow:
  1. `skilltap where <name>` → the folder in the source clone.
  2. Edit there, follow that repo's `CLAUDE.md`, commit with a real why, `git push`.
  3. `skilltap refresh` → installed copy updated.
- One clone per repo, shared by all its skills and all parallel agents: a push carries every local commit; unpublished work goes on a branch. `refresh` rebases clones (autostash) — while a peer edits a clone, don't refresh.
- Tracked or not? `skilltap status`. Untracked skill → edit in place.
- Origins: `user` (installed by hand) is never touched by `apply`; `list:<path>` skills come and go with that list.
- Per-host source override: `<root>/skilltap/config.json` `{"remap": {"<repo>": "<repo>"}}` reroutes list entries and `get` URLs (one host installs from a fork/mirror, others from the list's URL). Details → `references/how-it-works.md`.

## Commands

The surface is `skilltap --help` and `skilltap <command> --help`; read them before an unusual call.

| Need | Command |
|---|---|
| install from a link | `skilltap get <url>` or `skilltap get <git-url> <path>` |
| update everything now | `skilltap refresh` |
| what's tracked, what's stale | `skilltap status` (`--json` adds clone paths) |
| stop tracking / uninstall | `skilltap forget <name>` / `skilltap remove <name>` |
| admin skill list | `skilltap apply <list.json>` |
| set up auto-refresh | `skilltap hook` |

Not on PATH → `python3 ~/.claude/skills/skilltap/skilltap.py ...` (Windows: `python`).

File layout, refresh mechanics, list format, bootstrap on a new machine → `references/how-it-works.md`.

## Memory

`~/.claude/skilltap/memory.md`: local lessons, outside the skill (updates keep it). Read first; create on first write. Cost a question, retry or context → one imperative line now; why only if it prevents a mistake. Situational → `memory/<topic>.md` behind a `<trigger> → file` line. Every-user fact → skill defect (unsure → note; proven → move it in).

## Fix on friction

Gap, confusing/flooding/noisy output, stale text = skill defect; no silent workarounds. Small → fix now. Large → background `opus` teammate, one-message ticket (fact, proving command, output) fixing the faulty layer: SKILL.md, references/, scripts/, tool. Continue only if unblocked. Tracked (`skilltap status`) → edit its clone, pull, push; else in place.

- skilltap's own fixes go to its clone (`skilltap where skilltap`): change `skilltap.py`, add a test in `dev/tests/`, run `python3 -m unittest discover -s dev/tests` (green, seconds), commit, push, `skilltap refresh`.

> Source: https://github.com/nvaikus/skills/blob/main/skilltap/SKILL.md
