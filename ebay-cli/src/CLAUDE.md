# ebay — developer brief

Keep this file one screen. Entry `ebay.py` → `src/main.py:main`. Python 3.9+, stdlib only. Mirrors the gmail CLI's layout.

## Invariants — never break

- stdlib only. Read-only on the eBay API: `core/http.request` refuses non-GET without `allow_mutate=True`; only `api/auth` (token POST) passes it. A test greps `src/commands` for `http.request|allow_mutate|urllib|print(`.
- Account actions (cart, msg, login) only through `api/browser` + `api/js/*.js` (playwright-cli run-code). Never checkout, pay, bid, offer: a test greps `api/js` for those words. Every wait bounded (`browser.TIMEOUTS`); every action verifies its outcome on the page; failure returns a screenshot + ARIA dump. Not logged in → exit 5.
- A command never speaks HTTP and never prints: `api/` does the work, rows go to `ctx.write` / `ctx.text`.
- stdout = data; stderr = `# ` notes and `ebay: <error>`. Exit 0 · 1 · 2 · 5 setup waits on the user · 130. Branch on `e.status` / `http.error_ids(e)`, never on message text.
- Keys never in argv, config.json or output: env > macOS Keychain > `credentials.json` (600, warned), see `core/secrets.py`. `doctor` shows them masked.
- Config keys are contract (`core/config.DEFAULTS`); watch files (`api/watch.py`) too.

## Layers

| file | owns |
|---|---|
| `main.py` · `registry.py` · `context.py` | argv, `watch <verb>` family, globals, exit codes · name → (module, help) · ctx |
| `core/` | http (429 Retry-After, retries), output (TSV/JSON Writer), config, secrets, paths, errors |
| `api/auth.py` · `ebay.py` | client-credentials token cached in token.json · authorized GET, marketplace + end-user-context headers, error → exit code |
| `api/query.py` · `markets.py` | search flags → Browse params/filter, location (market, ship_to, zip) · currency + web domain per market |
| `api/browse.py` · `taxonomy.py` | search rows, item lookup (legacy / v1 / URL / item group), markdown card · category suggestions |
| `api/watch.py` | saved searches, seen state, new + drop detection |
| `api/setup.py` · `setup_say.py` | setup state machine + live verify · every user-facing setup text |
| `api/browser.py` · `account.py` · `js/` | playwright-cli runner (session, open, run-code, result → exit code, dumps) · ids/variation/seller → rows · one JS per action + `prelude.js` (selectors, `// live <date>` notes) |
| `commands/<area>/<cmd>.py` | argparse + orchestration, < ~60 lines |

## Add a command

1. `registry.COMMANDS["name"]` or `"watch verb"` = `("src.commands.<area>.<file>", "one-line help")`.
2. Module: `FIELDS`, `EPILOG` (2–4 examples + traps), `add_args(p)`, `run(ctx, args)`. Never declare `-j/--fields/--no-header`.
3. Tests in `dev/tests/` (import `support` first: temp `EBAY_ROOT`, fake keys in env, Keychain off). `FakeEbay` replaces `core.http.request`, routes by URL path, serves `fixtures/*.json`. Account commands: `FakePw` (`test_account.py`) replaces `browser._call`, reads the generated script, answers per action.

## Route discovery

Browse/Taxonomy truth = OpenAPI specs (the HTML reference pages answer 403 to scripts): developer.ebay.com/api-docs/master/buy/browse/openapi/3/buy_browse_v1_oas3.json, .../commerce/taxonomy/openapi/3/commerce_taxonomy_v1_oas3.json. Filter syntax: developer.ebay.com/api-docs/buy/static/ref-buy-browse-filters.html.

## Test

- `python3 -m unittest discover -s dev/tests` — mocked, no network, < 1 s.
- Live: `ebay doctor` (needs the user's keys). Account: `ebay cart list`, `ebay msg list` are safe; never test `cart add/rm` or `msg send` on the user's real account.
- JS in run-code: no `require`, no `URL` global in the page-function scope (inside `page.evaluate` the browser has both). Probe live DOM before changing a selector.
