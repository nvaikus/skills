# Rich text: markdown ⇄ ADF

Jira Cloud stores descriptions and comments as ADF json — many times the size of the text. `scripts/adf.py` (relative to the skill folder) converts both ways; the dialect is in `python3 scripts/adf.py --help`. Headings take a color: `## Actual result {#ba424c}`.

## Write

1. Compose markdown in the dialect, in a temp file (`/tmp/atlassian-cli/<KEY>.md`).
2. `python3 scripts/adf.py to-adf <KEY>.md > <KEY>.json`
3. Hand the json over: `--description-file <KEY>.json` on create/edit; comments — the file flag their leaf `--help` names.

## Read

`acli jira workitem view <KEY> --fields description --json | python3 scripts/adf.py to-md` — it finds the first doc node in any JSON, so no `jq` step can spill ADF into context. Comments: the same pipe on their `--json`.

## Images

1. Upload the file as an attachment (`references/rest.md`).
2. Media UUID ≠ attachment id. Ask for the attachment content without following the redirect; the target contains `/file/<uuid>/binary`:
   `curl -s -o /dev/null -w '%{redirect_url}' -u "$EMAIL:$TOKEN" https://<site>.atlassian.net/rest/api/3/attachment/content/<id>`
3. `![<file name>](<uuid> =<W>x<H>)` on its own line (or as a whole table cell) where it illustrates; W×H = the real pixel size.
4. Reconvert, `edit --description-file`.

## Mentions

`@[Name](accountId)`. acli has no user search — copy the accountId from any work item JSON where the person is reporter or assignee.

## adf.py exits 1

- The doc holds something outside the dialect; stderr names the node and mark types, stdout stays empty.
- That is a skill defect (Fix on friction): extend `scripts/adf.py` in both directions — to-md output must parse back to the same ADF — then retry.
- Done when `python3 scripts/adf.py check <failing-doc.json>` prints `OK` and the unit tests stay green.
- Never turn a real description into a test fixture (credentials, customer data); write a synthetic one.
