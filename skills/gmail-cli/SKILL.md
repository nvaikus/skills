---
name: gmail-cli
description: Gmail for agents, one stdlib CLI on macOS, Linux and Windows, several Google accounts at once. Search with Gmail query syntax across every connected account (merged TSV), read threads as compact markdown (quotes, signatures, HTML noise stripped), download attachments, organize (labels, archive, read/unread, star, trash; on ids or on everything a query matches), manage labels, write drafts and replies, send; declutter (top senders with unsubscribe method, one-click unsubscribe, Gmail filters). Guided onboarding in chat, reusing the gdrive OAuth key when present. Use when a task touches the user's email - "check my mail / inbox", "find the email from X", "what did X write", "unread mail", "reply to", "draft an email", "send email", "archive / label these", "clean up my inbox", "who spams me", "unsubscribe", "filter", "declutter", "Gmail", "mail", "inbox", "email", "письма", "почта", "ответь на письмо", labels, draft. NOT for Drive files (use google-drive-cli) or Calendar.
---

# gmail-cli

One profile = one Gmail account (`gmail profiles`). `search` and `draft list` cover every profile unless `--profile`; an ID finds its own account; everything else (labels, `-q` changes, new drafts) uses the default profile - name it with `--profile` when the user has several.

```
gmail profiles                                       # accounts here (start here); none -> onboard
gmail search 'from:anna is:unread newer_than:7d'     # Gmail query syntax; --limit 20, --threads
gmail read ID                                        # whole thread, compact; --message, --full
gmail attachment get ID 1 -o ~/Downloads/            # numbers from `read`
gmail archive ID... | -q QUERY                       # also mark-read, star, trash, un-*; --threads, --dry-run
gmail modify -q 'from:billing@x.com' --add Finance --remove INBOX
gmail label list | create A/B | rename OLD NEW | delete NAME
gmail draft create --to a@x.com --subject S --body - < body.txt     # --reply-to ID [--reply-all], --attach, --md
gmail draft show DRAFT_ID   ->   gmail draft send DRAFT_ID
gmail senders --profile work 'newer_than:1y' --min 5   # top senders: count, unread, category, unsubscribe
gmail unsubscribe --profile work a@x.com b@y.com --dry-run      # one-click POST > mailto > manual URL
gmail filter list | create --from a@x.com --archive --mark-read [--apply] | delete ID
```

## Onboarding

New account: `gmail onboard --profile NAME` (NAME = short label: work, personal). Each run prints one step: relay the text under "say to the user" word for word, then run the command under "then run" with the answer; repeat until `DONE`. Exit 5 = waiting on the user; exit 6 = Google still switching the API on, wait ~1 min and rerun. The redirect address the user pastes goes through stdin (`printf '%s' '<URL>' | gmail --profile NAME login --finish`), never as an argument.

## Writing mail

- Default: `draft create` → `draft show` → show the user what will go out → `draft send` after they agree. Direct `send` only when the user asked to send without review.
- Replies: `--reply-to ID` threads it, sets `Re:` and reply headers, addresses the sender; add `--reply-all` to Cc the rest. The quoted original and the Gmail web signature are NOT added: write the sign-off into the body.
- Body via `--body -` + stdin (heredoc) for anything multi-line; `--md` turns markdown into an HTML part.

## Declutter

- `senders` first (slow: Gmail's per-user quota caps reads at ~300-1000/min; run once, reuse the output). Then per sender: `unsubscribe` (column says how), `filter create` (archive/label/trash future mail; `--apply` = existing mail too), or `archive -q 'from:X'`. Show the user the plan, act after they agree; `unsubscribe --dry-run` first.
- `filter create/delete` exit 2 "Log in again" on logins older than filters: relay `gmail --profile NAME onboard --relogin` steps (same as onboarding: say, then `login --finish` via stdin). Mail keeps working meanwhile. `gmail profiles` column `filters` shows who needs it.

## Contract

- stdout TSV (`-j` JSON, `--fields a,b`, `--no-header`); stderr `# ` notes. `read` prints markdown.
- Exit `0` ok · `1` Google failure · `2` usage, no profile, not logged in, id/label not found · `5` onboarding waits on the user · `6` in progress, nothing undone, rerun.
- No confirmations: archive/label/trash act at once, `-q` acts on every match. Unsure how many → `--dry-run` first (prints `matched`). Trash only, no permanent delete; `untrash` restores for 30 days.
- IDs are per account; search's `profile` column says which. Message id ≠ thread id; both work for `read`.

| when | read |
|---|---|
| onboarding stuck, consent/login errors, API disabled, second account or machine, files on disk | `references/setup.md` |
| search misses mail, odd `read` output, labels/threads semantics, send-as, size limits, quota waits, unsubscribe/filter effects | `references/traps.md` |

## Memory

`~/.claude/gmail/memory.md`: local lessons, outside the skill (updates keep it). Read first; create on first write. Cost a question, retry or context → one imperative line now; why only if it prevents a mistake. Situational → `memory/<topic>.md` behind a `<trigger> → file` line. Every-user fact → skill defect (unsure → note; proven → move it in).

- Typical entries: which profile is which mailbox, labels the user means by nickname, recurring senders.

## Fix on friction

Gap, confusing/flooding/noisy output, stale text = skill defect; no silent workarounds. Small → fix now. Large → background `opus` teammate, one-message ticket (fact, proving command, output) fixing the faulty layer: SKILL.md, references/, scripts/, tool. Continue only if unblocked. Tracked (`skilltap status`) → edit its clone, pull, push; else in place.

- Code changes: read `src/CLAUDE.md` first; `python3 -m unittest discover -s dev/tests` must stay green.

> Source: https://github.com/nvaikus/skills/blob/main/skills/gmail-cli/SKILL.md
> Install via skilltap for auto-updates: https://github.com/nvaikus/skills/blob/main/skills/skilltap/SKILL.md
