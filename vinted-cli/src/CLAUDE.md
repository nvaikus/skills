# vinted — developer brief

Keep this file one screen. Entry `vinted.py` → `src/main.py:main`. Python 3.9+, stdlib only. Mirrors olx-cli's layout.

## Invariants — never break

- stdlib only. GET only: Vinted is never written to. Only `core/http.get` opens URLs (a test greps `src` for `urlopen`).
- `core/http.tls_context()` keeps `post_handshake_auth = False` (CDN bot filters fingerprint urllib's default ClientHello). A test pins it.
- Polite: `http.GAP` 1.5 s between requests per process (`VINTED_GAP`), `TIMEOUT` 25 s, retries only on 429/5xx/network.
- Every request outcome appends one line to `health.tsv`; refusals (Cloudflare challenge, 403/captcha HTML) and page-data changes raise `Broken` (exit 3). Schema guards: `vinted.need()`, `vinted.extract()`, `items.ITEM_KEYS`.
- A command never speaks HTTP and never prints: `api/` does the work, rows go to `ctx.write` / `ctx.text`. A test greps `src/commands` for `urllib|urlopen|http.get|print(`.
- stdout = data; stderr = `# ` notes and `vinted: <error>`. Exit 0 · 1 · 2 · 3 broke · 130. Branch on exception class / `e.status`, never on message text.
- Config keys (`core/config.DEFAULTS`) and watch files (`api/watch.py`) are contract.

## Layers

| file | owns |
|---|---|
| `main.py` · `registry.py` · `context.py` | argv, `watch <verb>` family, globals, exit codes · name → (module, help) · ctx |
| `core/` | http (pace, TLS, retries, refusal → Broken, health log, cookies), output (TSV/JSON Writer), config, paths, errors |
| `api/vinted.py` | sites, flight payload parsing (`self.__next_f.push`), catalog / item pages, ld+json, session cookie + brands JSON API |
| `api/items.py` | search row, paging (96/page, 10 pages) + `--must`, lookup by id/URL, item details + markdown card |
| `api/query.py` · `categories.py` · `filters.py` | search flags → `/catalog` params (names → ids) · catalogTree, cache, resolve · conditions, colors, brands, size probe |
| `api/watch.py` · `notify.py` | saved searches, seen state, new + drop · claude-tg message, failure de-dup |
| `commands/<area>/<cmd>.py` | argparse + orchestration, < ~60 lines |

## Add a command

1. `registry.COMMANDS["name"]` or `"watch verb"` = `("src.commands.<area>.<file>", "one-line help")`.
2. Module: `FIELDS`, `EPILOG` (2–4 examples + traps), `add_args(p)`, `run(ctx, args)`. Never declare `-j/--fields/--no-header`.
3. Tests in `dev/tests/` (import `support` first: temp `VINTED_ROOT`, `VINTED_GAP=0`). `FakeVinted` replaces `core.http.get`, routes by URL path, serves `fixtures/*` from `dev/record_fixtures.py`.

## Route discovery

No docs, and the old JSON API is closed to web clients. Data lives in the page's flight payload: fetch a page, join the `self.__next_f.push([1,"..."])` chunks, search for a key (`"items":{"items":[`, `"catalogTree":`, `"dynamicFilters":`, `"plugins":`, `"pricingServices":`) and `json.JSONDecoder().raw_decode` from there. Filter params = the web URL's (`catalog[]`, `brand_ids[]`, `size_ids[]`, `status_ids[]`, `color_ids[]`, `price_from`, `order`). Selected filter ids are echoed back with titles in `dynamicFilters`: that is how `sizes` learns names. URLs > ~19 KB → HTTP 431.

## Test

- `python3 -m unittest discover -s dev/tests` — mocked, no network, < 1 s.
- Live: `VINTED_LIVE=1 python3 -m unittest discover -s dev/tests -p test_live.py` or `vinted doctor`.
- Fixtures: `python3 dev/record_fixtures.py` (live, anonymizes sellers).
