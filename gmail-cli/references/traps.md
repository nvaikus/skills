# Traps (search, read, organize, send, declutter)

## Search
- Words without operators match anywhere incl. bodies, stemmed by Gmail; exact phrase needs quotes inside the query: `gmail search '"exact phrase"'`.
- Spam and Trash are excluded unless `--spam-trash` or `in:spam` / `in:trash` / `in:anywhere`.
- `label:` takes the label name with spaces/slashes as dashes (`label:clients-acme`) or quoted (`label:"Clients/Acme"`).
- `newer_than:2d` counts from now; `after:2026/01/31` = midnight Pacific time, exact cutoff = epoch seconds (`after:1769817600`). Output `date` is this machine's local time.
- Default row = one message; the web UI shows conversations. `--threads` gives one row per thread (row = last message, `count` = messages).
- Cross-account search: `--limit` applies to the merged list; a logged-out profile is skipped with a `#` note, not an error.

## Read
- Quote stripping is heuristic (Gmail/Apple/Outlook headers in EN/RU/PT/ES/DE/FR/IT/NL/PL, `> ` lines, `-- ` signatures, "Sent from my ..."). Missing context → `--full`.
- Long messages cut at 6000 chars per message; the cut line names the command for the rest.
- Reading never marks as read; `mark-read` does.

## Organize
- Archive = remove `INBOX`; the message stays in All Mail. Category tabs are labels `CATEGORY_*` (shown without the prefix; `modify --add PROMOTIONS` works).
- Labels act per message; Gmail's UI shows a thread labeled if any message is. `--threads` widens to whole conversations.
- Gmail ids are per account: an id from one profile is unknown in another (`read` / changes find the right one, default profile first).
- `label delete` keeps nested labels; `label rename` moves them.

## Drafts and send
- The API never adds the Gmail web signature nor quotes the original on reply.
- `--from` must be a verified send-as alias of the account; otherwise Gmail silently sends from the main address.
- Messages over ~4.5 MB go through the upload endpoint automatically; Gmail's own cap is 25 MB of attachments (35 MB raw).
- `draft edit` rebuilds the message: an HTML part made by `--md` is regenerated from the markdown; a draft written in the web UI loses its rich formatting (plain text kept).
- `draft send` / `send` cannot be undone (no undo-send window via the API).

## Declutter
- Quota: per user per OAuth project, a sliding 60 s window; this client's project allows 6000 units/min and a metadata read really costs ~15-20, so bulk scans run ~300 reads/min (3000 messages ≈ 6-10 min). The first `# quota reached` note is normal pacing, not a failure. Faster only via a quota increase in the Cloud console (Gmail API → Quotas → per-user).
- `unsubscribe` acts on the sender's side, often days later; meanwhile mail keeps arriving: pair it with `filter create --from X --archive`. A mailto unsubscribe lands in Sent. `manual` = a URL the user opens (the CLI never GETs it).
- `senders` groups by exact From address: one brand often mails from several (`news@`, `offers@`); sum them by domain before deciding.
- Filters act on new mail only; `--apply` runs the same change on existing matches.
