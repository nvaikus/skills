---
name: google-drive-cli
description: Google Drive as a local filesystem plus Google Docs and Sheets by path, with a grep-able text index of the whole Drive, one CLI on macOS, Linux and Windows. Guided onboarding of a Google account (profile) step by step in chat; mounts everything (My Drive, Shared with me, Shared drives), a folder or a Shared drive at a local dir (rclone mount / nfsmount, or a synced folder where mounting is impossible), so files are read and written with normal tools; Google Docs are read as markdown and edited in place, Sheets read and written as TSV; every file's text (docx/xlsx/pptx/PDF/scans/Google files) is mirrored into markdown kept fresh every 5 min for rg search. Use when a task touches the user's Google Drive - "find in Drive / in our documents", "which file mentions X", "open/read the file on Drive", "put this on Drive", "connect/set up Google Drive", "mount Google Drive", "what does the Doc say", "update the Google Doc", "add a row to the sheet", "share link", a docs.google.com URL, "gdrive". NOT for Gmail (use gmail-cli) or Calendar.
---

# google-drive-cli

One profile = one Google account (or Shared drive): its mount, its login, its text index.
A profile mounting `/` shows `<dir>/My Drive/`, `<dir>/Shared with me/` (flat list of what others shared) and `<dir>/Shared drives/<name>/`. Addresses: `/A/B` (My Drive), `shared-with-me:/Name/...`, `shared:<Drive>/...`, URL, `@<id>`.

```
gdrive profiles                                  # accounts here, where each is mounted (start here)
gdrive profiles --rename OLD NEW                 # umount OLD's mounts first, mount again after
gdrive status                                    # mounts: state, pending uploads
gdrive onboard --profile NAME                    # set up a new account, one step per run
gdrive doc cat /Projects/Plan                    # Google Doc -> markdown
gdrive doc edit /Projects/Plan --replace OLD NEW | --append MD | --after HEADING MD
gdrive sheet get /Finance/Budget "Q3!A1:F20"     # TSV; sheet set / append read TSV on stdin
gdrive sync ~/gdrive/work                        # wait until writes are on Drive
```

Invoke `python3 ~/.claude/skills/google-drive-cli/gdrive.py` (Windows: `python %USERPROFILE%\.claude\skills\google-drive-cli\gdrive.py` or `gdrive.cmd`). The surface is `gdrive --help` / `gdrive <cmd> -h` - grep it, don't guess flags. Several profiles: `--profile NAME` (a path inside a mount picks its own profile).

## Set up an account (onboarding)

Loop until exit 0: run `gdrive onboard --profile NAME` → exit 5 prints `--- say to the user ---` (relay it WORD FOR WORD, the user is not technical) and `--- then run ---` (run it with the user's answer) → run onboard again. `--- then run (right away, no answer needed) ---` and exit 6: relay, then run it at once (it waits up to ~200 s for the browser job). Every run re-checks everything live and never repeats finished work; exit 0 `DONE` = mounted, autostart set, index building in background. NAME: short lowercase label (`work`, `njdesign`).

Step 2 asks the user: automatic (a Chrome window opens on THIS machine; the user signs in, clicks "Continue" once) or manual (step-by-step texts). Automatic needs a screen here - offered only when available; a step it cannot do falls back to that step's manual text.

## Find something

1. `rg -n -i "words" ~/.claude/gdrive/<profile>/index/` (`-l` for names only; narrow before it reaches context).
2. Hit `index/<rel>.md` → the original is `<mount dir>/<rel>` (mount dir: `gdrive profiles`). A segment `name@<id>` = duplicate names: use the header's `address:` with `gdrive doc|sheet|ls|link`.
3. Read or edit the ORIGINAL; never answer from the index text alone - it lags up to ~10 min (header `indexed:`), and is lossy (no images, layout, formulas).
4. After writing an original: `gdrive sync <dir>`, then `gdrive index update <path>`.

Index missing, stale or incomplete: `gdrive index status`.

### Shared files: indexed on demand
The index of a `/` profile covers only My Drive (`index status` → `sections`). Shared with me / Shared drives are in the mount, not in the index, until included:
- Trigger: the user talks about files shared with them / a Shared drive, or step 1 finds nothing and the file may live there.
- Run `gdrive index include shared-with-me` (or `shared-drives`, `"shared:<Drive>"`), tell the user "indexing <files> shared files now" (the `files` column), then search; texts arrive in the background (`pending` → `index status`), the finished part is searchable at once.
- Before that (or instead): read them via the mount or `gdrive ls shared-with-me:`. `index exclude` undoes it.

## Contract

- stdout TSV (`-j` JSON, `--fields a,b`, `--no-header`); stderr `# ` notes. Narrow before it reaches context.
- Exit `0` ok · `1` Google/rclone failure · `2` usage, no profile, not logged in, path not found or ambiguous (candidates listed as `name@id` - pick one, never retry the same path) · `3` refused by a rail, nothing changed · `5` onboarding waits on the user · `6` wait deadline, nothing undone - rerun to keep waiting.
- Google Docs/Sheets/Slides are never converted: in a mount they are `.docx/.xlsx/.pptx` EXPORTS (macOS: 0 bytes, read EMPTY) - read them with `doc cat`/`sheet get` or in the index, not via the mount; change them only with `doc`/`sheet`. Saving an export uploads a SEPARATE Office file next to the Google one.
- A write in the mount is on Drive only after `gdrive sync <dir>` returns 0. Say "uploaded" only after that.
- No full rewrite of a Google Doc exists on purpose (it would drop comments and formatting): targeted `doc edit` only.
- `link` without `--public` changes nothing; `--public` shares with anyone who has the link - only when the user asked.
- `share PATH` lists access (`inherited` = from a parent folder); `--user EMAIL` / `--remove EMAIL` change it - only when the user asked. Moving an item out of a shared folder drops its inherited access: check `share` before/after a reorganization.

| when | read |
|---|---|
| onboarding stuck, login/consent errors, 7-day logouts, a second machine, layout on disk | `references/setup.md` |
| a mount misbehaves (stale, hang, busy, missing files), a sync folder conflicts, exports/duplicates confuse | `references/traps.md` |
| index results look wrong, missing, stale; OCR, big files, errors in `index status` | `references/index.md` |

## Memory

`~/.claude/gdrive/memory.md`: local lessons, outside the skill (updates keep it). Read first; create on first write. Cost a question, retry or context → one imperative line now; why only if it prevents a mistake. Situational → `memory/<topic>.md` behind a `<trigger> → file` line. Every-user fact → skill defect (unsure → note; proven → move it in).

- Typical entries: which profile holds which business, folder paths the user refers to by nickname, ids of duplicate-named files.

## Fix on friction

Gap, confusing/flooding/noisy output, stale text = skill defect; no silent workarounds. Small → fix now. Large → background `opus` teammate, one-message ticket (fact, proving command, output) fixing the faulty layer: SKILL.md, references/, scripts/, tool. Continue only if unblocked. Tracked (`skilltap status`) → edit its clone, pull, push; else in place.

- Code changes: read `src/CLAUDE.md` first; `python3 -m unittest discover -s dev/tests` must stay green.

> Source: https://github.com/nvaikus/skills/blob/main/google-drive-cli/SKILL.md
> Install via skilltap for auto-updates: https://github.com/nvaikus/skills/blob/main/skilltap/SKILL.md
