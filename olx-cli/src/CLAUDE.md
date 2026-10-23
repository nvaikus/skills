# olx — developer brief

Keep this file one screen. Entry `olx.py` → `src/main.py:main`. Python 3.9+, stdlib only. Mirrors ebay-cli's layout.

## Invariants — never break

- stdlib only. GET only: OLX is never written to. Only `core/http.get` opens URLs (a test greps `src` for `urlopen`).
- `core/http.tls_context()` keeps `post_handshake_auth = False`: CloudFront 403s urllib's default ClientHello. A test pins it.
- Polite: `http.GAP` 1 s between requests per process (`OLX_GAP`), bounded timeout, retries only on 429/5xx/network.
- Every request outcome appends one line to `health.tsv`; refusals (403/captcha HTML) and JSON-shape changes raise `Broken` (exit 3). Schema guards: `olx.need()`, `offers.OFFER_KEYS`.
- A command never speaks HTTP and never prints: `api/` does the work, rows go to `ctx.write` / `ctx.text`. A test greps `src/commands` for `urllib|urlopen|http.get|print(`.
- stdout = data; stderr = `# ` notes and `olx: <error>`. Exit 0 · 1 · 2 · 3 broke · 130. Branch on exception class / `e.status`, never on message text.
- Config keys (`core/config.DEFAULTS`) and watch files (`api/watch.py`) are contract.

## Layers

| file | owns |
|---|---|
| `main.py` · `registry.py` · `context.py` | argv, `watch <verb>` family, globals, exit codes · name → (module, help) · ctx |
| `core/` | http (pace, TLS, retries, refusal → Broken, health log), output (TSV/JSON Writer), config, paths, errors |
| `api/olx.py` | sites, endpoint helpers (offers, offer, geo, search-categories, home/ad HTML), URL → id |
| `api/offers.py` | price kinds, row, paging + promoted drop + `--must`, lookup, markdown card |
| `api/query.py` · `categories.py` | search flags → offers params (names → ids) · category tree from home `__PRERENDERED_STATE__`, cache, resolve |
| `api/photos.py` | full-size photo links, download (`http.get(want="bytes")`), contact sheet via ffmpeg subprocess if on PATH |
| `api/watch.py` · `notify.py` | saved searches, seen state, new + drop · claude-tg message, failure de-dup |
| `commands/<area>/<cmd>.py` | argparse + orchestration, < ~60 lines |

## Add a command

1. `registry.COMMANDS["name"]` or `"watch verb"` = `("src.commands.<area>.<file>", "one-line help")`.
2. Module: `FIELDS`, `EPILOG` (2–4 examples + traps), `add_args(p)`, `run(ctx, args)`. Never declare `-j/--fields/--no-header`.
3. Tests in `dev/tests/` (import `support` first: temp `OLX_ROOT`, `OLX_GAP=0`). `FakeOlx` replaces `core.http.get`, routes by URL path, serves `fixtures/*` recorded live.

## Route discovery

No docs: watch the site's own XHRs (browser devtools on olx.pt search) or probe with curl over HTTP/2. Filter params are the web URL's `search[...]` names flattened (`filter_float_price:from`, `filter_enum_<param>[0]`). 400 bodies list the bad field under `error.validation`.

## Test

- `python3 -m unittest discover -s dev/tests` — mocked, no network, < 1 s.
- Live: `OLX_LIVE=1 python3 -m unittest dev/tests/test_live.py` or `olx doctor`.
