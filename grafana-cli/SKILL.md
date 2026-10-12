---
name: grafana-cli
description: Drives Grafana (OSS, Enterprise, Cloud; Grafana 12+) through gcx, Grafana's official CLI (successor of the deprecated grafanactl) - dashboards (list, search, get, export, import, versions, PNG snapshots), folders, datasources (list, health, query - ClickHouse, Prometheus, Loki, SQL, any type), alert rules, raw HTTP API calls, resources-as-code pull/push. Read before the first gcx call of a session. Use when a task inspects or changes a Grafana instance or queries data through a Grafana datasource. NOT for querying ClickHouse directly without Grafana (clickhouse-cli). Triggers - gcx, grafanactl, Grafana, dashboard, panel, datasource, export dashboard JSON, import a dashboard, Grafana API, alert rule, Explore query.
---

# grafana-cli

`gcx` is one Go binary. Auth and instance live in named contexts (`~/.config/gcx/config.yaml`); env vars override the selected context per call. Grafana ships its own task skills inside the binary; this skill covers setup and the traps.

## Every run

- Flags from help, never guessed: `gcx help-tree` (whole tree, compact), then `gcx <cmd> --help`. Help footers name a bundled skill; read it only if it fits the task: `gcx agent skills get <name> -otext` (`gcx agent skills list` = all 24).
- Inside Claude Code gcx is in agent mode (JSON, `{"class":"hint"}` lines first). Shrink at the source: `--json f1,f2`, `--jq '<expr>'`, `-o table`, `--limit N`.
- Instance = `--context <name>` per call; never `gcx config use-context` (global state; parallel agents race on it).
- Orgs (self-hosted): a service-account token is bound to one org → one context per org. With user/password, `org-id`/`GRAFANA_ORG_ID` steers only `dashboards`/`resources`; `datasources` and `api` stay in the user's current org (`gcx api` takes `-H 'X-Grafana-Org-Id: <n>'`).
- Writes (`create`, `update`, `push`, `api -X POST/PUT`) only inside the task; `delete` only on an explicit request. Never set `GCX_AUTO_APPROVE`.

| When | Read |
|---|---|
| `gcx` missing, no context, 401/403, "Keychain unavailable", "node not found", "missing ... org-id" | `references/setup.md` |
| Exporting / importing / diffing dashboards, querying a datasource, raw API | `references/recipes.md` |

## Memory

`~/.claude/grafana-cli/memory.md`: local lessons, outside the skill (updates keep it). Read first; create on first write. Cost a question, retry or context → one imperative line now; why only if it prevents a mistake. Situational → `memory/<topic>.md` behind a `<trigger> → file` line. Every-user fact → skill defect (unsure → note; proven → move it in).

- Typical entries: context name → instance and what it is for, org ids, default datasource uids, which dashboards are provisioned from files (edit the source, not Grafana).

## Fix on friction

Gap, confusing/flooding/noisy output, stale text = skill defect; no silent workarounds. Small → fix now. Large → background `opus` teammate, one-message ticket (fact, proving command, output) fixing the faulty layer: SKILL.md, references/, scripts/, tool. Continue only if unblocked. Tracked (`skilltap status`) → edit its clone, pull, push; else in place.

> Source: https://github.com/nvaikus/skills/blob/main/grafana-cli/SKILL.md
> Install via skilltap for auto-updates: https://github.com/nvaikus/skills/blob/main/skilltap/SKILL.md
