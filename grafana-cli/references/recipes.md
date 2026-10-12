# Recipes

All with `--context <ctx>` (omitted below).

## Dashboards

- Find: `gcx dashboards search "<words>"`; uid = the `NAME` column.
- `gcx dashboards get <uid> -o json` returns the new v2 resource schema (`apiVersion dashboard.grafana.app/v2`), not the classic dashboard JSON.
- Classic JSON (what the UI exports and file provisioning reads): `gcx api /api/dashboards/uid/<uid> --jq .dashboard > <uid>.json`.
- Import classic JSON: `mkdir -p /tmp/grafana-cli && jq '{dashboard: (. | del(.id)), folderUid: "<folder-uid>", overwrite: true}' <uid>.json > /tmp/grafana-cli/body.json && gcx api /api/dashboards/db -d @/tmp/grafana-cli/body.json`.
- Resources-as-code: `gcx resources pull dashboards -p <dir>` / `gcx resources push dashboards -p <dir>`; `gcx resources validate` before a push.
- `pull` silently skips resources managed by another tool (file provisioning, Terraform): "0 resources pulled" → add `--include-managed`. Such dashboards are owned by their source files: edit the source, not Grafana.
- PNG of a dashboard for a visual check: `gcx dashboards snapshot <uid> --timeout 3m` (needs the image renderer on the server).
- History: `gcx dashboards list-versions <uid>`.

## Datasource queries

- `gcx datasources list` → uid; typed subcommands per type (`gcx datasources clickhouse|prometheus|loki|postgres|... query`), `gcx datasources query <uid> '<expr>'` for anything else.
- SQL datasources take the uid by `-d <uid>` (not positional; positional = the query). Grafana macros work: `WHERE $__timeFilter(<time_col>) --since 7d`.
- Default `--limit 100` rows; `--limit 0` lifts it. `--share-link` prints an Explore URL for the user.
- The query runs as the datasource's own DB user (often read-only), not as the Grafana user.

## Raw API

- `gcx api <path>` uses the context's auth; `-d @file` implies POST; `-X` for others; `-o yaml|json`; `--jq`.
- Another org with user/password auth: `-H 'X-Grafana-Org-Id: <n>'` (`GRAFANA_ORG_ID` is ignored by `api`).
