---
name: clickhouse-cli
description: Queries and manages ClickHouse servers (self-hosted or ClickHouse Cloud) through the official `clickhouse client` (native protocol), plus `clickhouse local` for SQL over local files (CSV, Parquet, JSON) without a server; points to `clickhousectl` for ClickHouse Cloud service management. Named connections with passwords from env, output formats (TSV, JSONEachRow, CSV, Pretty, Markdown), query parameters, inserts from files, schema inspection, remote servers over TLS or an SSH tunnel. Read before the first clickhouse call of a session. Use when a task runs SQL on ClickHouse, inspects its tables, loads or exports data. NOT for querying through a Grafana datasource (grafana-cli). Triggers - ClickHouse, clickhouse client, clickhouse-client, clickhouse local, ClickHouse Cloud, clickhousectl, MergeTree, system.tables, JSONEachRow.
---

# clickhouse-cli

`clickhouse` is one binary: `clickhouse client` (talks to a server over the native protocol), `clickhouse local` (embedded engine over files, no server), `clickhouse format`, etc. Servers are named connections in the client config; passwords come from env, never from argv or the config text.

## Every run

- Flags from `clickhouse client --help`; SQL and settings from the docs (https://clickhouse.com/docs), never guessed.
- One query = `clickhouse client --connection <name> -q "<sql>"` (several statements: `-n`). Never interactive.
- Piped output defaults to `TabSeparated` without a header. Pick the format for the reader: `-f TSVWithNames` (compact), `-f JSONEachRow` (to jq), `-f Markdown` (to show the user), `-f PrettyCompactMonoBlock` (humans). Always `LIMIT` exploratory queries.
- Values into SQL only as typed parameters: `-q "SELECT ... WHERE id = {id:UInt64}" --param_id=42`; never string-concatenated.
- Read-only by default: `SELECT`, `SHOW`, `DESCRIBE`, `EXPLAIN`, `system.*`. `INSERT`/`CREATE`/`ALTER` only inside the task; `DROP`/`TRUNCATE`/`DELETE`/`ALTER ... DELETE` only on an explicit request. A read-only user rejects writes (`readonly=1` also rejects `SET` and per-query settings) - expected, not a bug.

| When | Read |
|---|---|
| `clickhouse` missing, no connection yet, auth errors, server only reachable remotely, ClickHouse Cloud | `references/setup.md` |
| Schema discovery, loading or exporting data, querying files, slow or memory-limited queries | `references/recipes.md` |

## Memory

`~/.claude/clickhouse-cli/memory.md`: local lessons, outside the skill (updates keep it). Read first; create on first write. Cost a question, retry or context → one imperative line now; why only if it prevents a mistake. Situational → `memory/<topic>.md` behind a `<trigger> → file` line. Every-user fact → skill defect (unsure → note; proven → move it in).

- Typical entries: connection name → server and what lives there, which user is read-only, key tables and their time columns.

## Fix on friction

Gap, confusing/flooding/noisy output, stale text = skill defect; no silent workarounds. Small → fix now. Large → background `opus` teammate, one-message ticket (fact, proving command, output) fixing the faulty layer: SKILL.md, references/, scripts/, tool. Continue only if unblocked. Tracked (`skilltap status`) → edit its clone, pull, push; else in place.

> Source: https://github.com/nvaikus/skills/blob/main/clickhouse-cli/SKILL.md
> Install via skilltap for auto-updates: https://github.com/nvaikus/skills/blob/main/skilltap/SKILL.md
