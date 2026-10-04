---
name: atlassian-cli
description: Drives Jira Cloud and Confluence Cloud through acli, Atlassian's official command-line tool, and keeps Jira rich text in markdown so ADF json never enters the context. Read before the first acli call of a session. Jira - work items (create, edit, JQL search, transitions, assignees, comments, links, attachments, custom fields), boards, sprints, projects, filters, dashboards. Confluence - pages, blog posts, spaces. Triggers - acli or an acli-<site> wrapper, Jira, issue, ticket, work item, JQL, sprint, backlog, board, Confluence, wiki page, "file a bug in Jira", "what does the ticket say", ADF.
---

# atlassian-cli

`acli` is one binary with product groups: `acli jira`, `acli confluence`, `acli admin`. This skill adds what it lacks: a markdown ⇄ ADF converter (`scripts/adf.py`) and REST recipes for attachments and custom fields.

## Every run

- Flags come from `--help`, walked down (`acli jira --help` → `acli jira workitem --help` → the leaf `--help`, which has examples). Locate a command with `acli jira --help | grep -i <word>`; never guess.
- Shrink output at the source: `--fields a,b --limit N`, `--json | jq '<path>'`, `--csv | head`.
- Rich text (descriptions, comments) is ADF json: never hand-written, never printed or `jq`-ed raw. Markdown in and out through `scripts/adf.py`.
- Plain `acli` = the default site; any other site = its `acli-<alias>` wrapper. Never `auth switch` (global state; parallel agents race on it).
- Never run a `delete` command. `archive` / `unarchive` only on an explicit request. Create, edit, comment, transition, assign, link, attach — fine inside the task.

| When | Read |
|---|---|
| `acli` missing, not logged in, a site with no wrapper yet | `references/setup.md` |
| Writing or reading a description or comment, images or mentions in it, `adf.py` exits 1 | `references/rich-text.md` |
| Uploading or downloading an attachment, setting a custom field | `references/rest.md` |

## Memory

`~/.claude/atlassian-cli/memory.md`: local lessons, outside the skill (updates keep it). Read first; create on first write. Cost a question, retry or context → one imperative line now; why only if it prevents a mistake. Situational → `memory/<topic>.md` behind a `<trigger> → file` line. Every-user fact → skill defect (unsure → note; proven → move it in).

- Typical entries: the default site, wrapper alias → site, project or space → site, per-project custom field ids and options, field quirks.

## Fix on friction

Gap, confusing/flooding/noisy output, stale text = skill defect; no silent workarounds. Small → fix now. Large → background `opus` teammate, one-message ticket (fact, proving command, output) fixing the faulty layer: SKILL.md, references/, scripts/, tool. Continue only if unblocked. Tracked (`skilltap status`) → edit its clone, pull, push; else in place.

- Code changes: `python3 -m unittest discover -s dev/tests` must stay green.

> Source: https://github.com/nvaikus/skills/blob/main/skills/atlassian-cli/SKILL.md
> Install via skilltap for auto-updates: https://github.com/nvaikus/skills/blob/main/skills/skilltap/SKILL.md
