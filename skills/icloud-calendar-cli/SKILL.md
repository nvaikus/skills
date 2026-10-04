---
name: icloud-calendar-cli
description: iCloud Calendar for agents over CalDAV, one stdlib CLI on macOS, Linux and Windows (no Mac needed); changes sync to Calendar on Mac, iPhone and icloud.com. List calendars with their kind (own, shared by me, shared with me rw/ro, subscribed, reminders), list events in a range (recurring ones expanded), show, add, edit, delete events; pending share invitations. Guided onboarding in chat with an app-specific password. Use when a task touches the user's Apple / iCloud calendar - "what's on my calendar", "am I free on", "schedule / add / book / move / cancel a meeting", "put it in my calendar", "events next week", "iCloud calendar", "Apple Calendar", "календарь", "запиши в календарь", "что у меня завтра". NOT for Google Calendar, nor Reminders/to-dos.
---

# icloud-calendar-cli

One profile = one Apple ID (`icloud-calendar profiles`). Calendars are named by name (case-insensitive, unique substring ok) or id (`calendars` column `id`).

```
icloud-calendar profiles                                   # Apple IDs here (start here); none -> onboard
icloud-calendar calendars                                  # name kind access owner comps color sharees default id
icloud-calendar list                                       # next 7 days, all event calendars; --from/--to/--days, --cal X, --grep
icloud-calendar list --from mon --to fri --cal Work -j
icloud-calendar show UID                                   # markdown; uid or >= 6 leading chars of it; -j adds raw ics
icloud-calendar add --title Dentist --start 'tomorrow 14:00' --duration 45m --alarm 1h [--cal Family]
icloud-calendar add --title Trip --start 2026-10-10 --end 2026-10-12 --all-day     # --end inclusive
icloud-calendar edit UID --start 'fri 15:00'               # keeps duration; --title --end --location --geo --no-geo --notes --alarm --no-alarms --timed
icloud-calendar delete UID                                 # --dry-run first when unsure
icloud-calendar invites                                    # pending share invitations (read-only)
icloud-calendar calendars --set-default NAME               # where `add` goes without --cal
```

## Calendar kinds

| kind | write | note |
|---|---|---|
| `own` | yes | |
| `shared-by-me` | yes | sharees see it (iCloud notifies them) - tell the user |
| `shared-with-me` rw | yes | the event lives in the owner's calendar; owner sees it |
| `shared-with-me` ro | refused (exit 2) | |
| `subscribed` | refused | read from the public feed |
| `reminders` | refused | to-do lists; never listed in `list` |

## Onboarding

New Apple ID: `icloud-calendar onboard --profile NAME` (first one: `main`). Each run prints one step: relay the text under "say to the user" word for word, run the command under "then run" with the answer; repeat until `DONE`. Exit 5 = waiting on the user. The app-specific password never goes through the chat, argv or a file: the user stores it in the OS keychain and exports `ICLOUD_APP_PASSWORD`; offer to add the export line (it holds no secret) and say Claude needs a restart to see it.

## Writing events

- Confirm with the user before touching an event in a shared calendar (other people see it) and before `delete`. Own calendars: act at once.
- Times are the machine's zone (`--tz` / `profiles --set-tz` to change); output shows the same zone.
- `edit`/`delete` act on the whole series of a recurring event (no single-occurrence edits); say so when the uid is recurring.
- Attendees / invitations to people are not supported: put names in `--notes`.
- `--location` is geocoded (OpenStreetMap) and pinned, so Calendar opens it in Maps; check the `# location pinned at ... :` note names the right place, else `--geo LAT,LON` or `--no-geo` (plain text). No match = plain text + a note.
- Alerts: no `--alarm` on a timed event = profile defaults (`profiles --set-alarms 1d,1h --set-alarms-today 2h,1h`; past triggers dropped); `--no-alarm` = none. Links (listing, ticket) go to `--url`.

## Contract

- stdout TSV (`-j` JSON, `--fields a,b`, `--no-header`); stderr `# ` notes. `show` prints markdown.
- Exit `0` ok · `1` iCloud failure (412 = changed elsewhere, rerun) · `2` usage, no profile, bad password, calendar/event not found or ambiguous, write refused by kind · `5` onboarding waits on the user.
- No confirmations inside the CLI: writes act at once; `--dry-run` prints the iCalendar instead.

| when | read |
|---|---|
| onboarding stuck, 401, second Apple ID, another machine / headless server, files on disk | `references/setup.md` |
| missing or odd events, kinds/access look wrong, recurring events, time zones, all-day ends, 412/403, deleted by mistake, location not clickable / wrong map pin | `references/traps.md` |

## Memory

`~/.claude/icloud-calendar/memory.md`: local lessons, outside the skill (updates keep it). Read first; create on first write. Cost a question, retry or context → one imperative line now; why only if it prevents a mistake. Situational → `memory/<topic>.md` behind a `<trigger> → file` line. Every-user fact → skill defect (unsure → note; proven → move it in).

- Typical entries: which calendar the user means by a nickname, who shares which calendar, the usual default for work vs family events.

## Fix on friction

Gap, confusing/flooding/noisy output, stale text = skill defect; no silent workarounds. Small → fix now. Large → background `opus` teammate, one-message ticket (fact, proving command, output) fixing the faulty layer: SKILL.md, references/, scripts/, tool. Continue only if unblocked. Tracked (`skilltap status`) → edit its clone, pull, push; else in place.

- Code changes: read `src/CLAUDE.md` first; `python3 -m unittest discover -s dev/tests` must stay green.

> Source: https://github.com/nvaikus/skills/blob/main/skills/icloud-calendar-cli/SKILL.md
> Install via skilltap for auto-updates: https://github.com/nvaikus/skills/blob/main/skills/skilltap/SKILL.md
