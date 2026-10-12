# Recipes

`ch` below = `clickhouse client --connection <name>`.

## Schema discovery

- `ch -q "SHOW DATABASES"`, `ch -q "SHOW TABLES FROM <db>"`, `ch -q "DESCRIBE TABLE <db>.<t>" -f TSV`.
- Sizes and row counts without scanning: `ch -q "SELECT name, engine, total_rows, formatReadableSize(total_bytes) FROM system.tables WHERE database = '<db>'" -f PrettyCompactMonoBlock`.
- `SHOW CREATE TABLE <db>.<t>`: the `ORDER BY` key is what filters fast; `PARTITION BY` / `TTL` explain missing old rows. Views and materialized views show their source query here.

## Loading and exporting

- Insert from a file: `ch -q "INSERT INTO <db>.<t> FORMAT CSVWithNames" < data.csv` (also `JSONEachRow`, `Parquet`, `TSVWithNames`). Columns not in the file get defaults.
- Export: `ch -q "SELECT ..." -f Parquet > out.parquet` (or `CSVWithNames`, `JSONEachRow`); the file is written on the client side.
- Big result for the user: write a file and report its path + row count, never print it.

## Files without a server

- `clickhouse local -q "SELECT ... FROM file('data.csv')"`: schema inferred from CSV/TSV/JSON/Parquet; check it with `DESCRIBE file('<path>')`. Globs work: `file('logs/*.json')`.
- Convert formats: `clickhouse local -q "SELECT * FROM file('in.csv')" -f Parquet > out.parquet`.
- Join a local file with a server table: `clickhouse local -q "SELECT ... FROM file('ids.csv') JOIN remoteSecure('<host>:9440', '<db>.<t>', '<user>', '<password>') USING id"` - only with the password from env (`$CLICKHOUSE_<NAME>_PASSWORD`), never typed.

## Heavy queries

- Settings as flags: `--max_execution_time=30`, `--max_memory_usage=2000000000`, `--max_threads=2`; `-t` prints the elapsed time to stderr.
- `MEMORY_LIMIT_EXCEEDED` on a small server → narrower time range on the `ORDER BY` key, `LIMIT` before `JOIN`, `--max_bytes_before_external_group_by`.
- Why slow: `EXPLAIN indexes = 1 SELECT ...` (granules read vs total).
