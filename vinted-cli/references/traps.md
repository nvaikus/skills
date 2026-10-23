# vinted-cli traps (live-checked 2026-10-23)

## Results

- Source = the `/catalog` web page's Next.js flight data, 96 rows per page, at most 10 pages: 960 rows is the hard window of any query (`total` notes are capped there too). Narrow filters to reach the rest.
- Results span the site's whole shipping area (vinted.pt shows FR/ES/IT sellers too). Neither rows nor item pages expose a location: no "near me" filter.
- Query is fuzzy (descriptions, other languages, other categories). `--must w1,w2` keeps titles containing every word (prefix, accents ignored) and scans only `--limit` rows, so it can return fewer.
- Promoted items are mixed in and obey the filters; kept, flagged `promoted` in `-j`, counted in the stderr note.
- `total` = price + buyer-protection fee as Vinted shows it; shipping is extra (`show`: "from X" = cheapest option, may be 0 during promos).
- Unknown ids (size from another category, made-up brand id) are ignored silently by Vinted: more rows, not an error. Sizes depend on the category: look them up with `vinted sizes --category <the category you search>`.
- Names (categories, conditions in rows, colors in cards) are in the site's language; filter names in the CLI are English and site-independent (`vinted conditions`, `vinted colors`). Category `--grep` also matches the English URL slug ("trainers").
- `--brand NAME` takes the exact match, else the top hit of Vinted's brand search (stderr says which). Ambiguous `--category NAME` → exit 2 with the candidate ids.
- `--currency` sets the currency of the price filter only; rows stay in the site currency (GBP co.uk, PLN pl, CZK cz ...).
- Item pages carry their own size/status ids (another id space): never feed them to `--size` / `--condition`.

## Watches

- Saved with resolved ids + site at add time; run uses newest-first order and the saved `--limit` (default 50).
- `new` = id never seen by this watch. `drop OLD>NEW` = item price fell, same currency. Seen state forgets ids unseen for 60 days. Sold items just vanish (not reported).
- State: `~/.claude/vinted/watch/` (`searches.json`, `seen/<name>.json`, `alerted.json`). Override root: `VINTED_ROOT`.
- `--notify` topic `vinted` must exist in claude-tg `notify_topics` (not registered by this skill).

## When it breaks (exit 3)

- Unofficial source: Cloudflare or a page redesign can stop it any day. Every request outcome goes to `~/.claude/vinted/health.tsv` (`ts host path ok|blocked|schema|http|network detail`); `vinted doctor` shows 30-day counts and the last failure.
- "Cloudflare challenge" = HTTP 403 "Just a moment / Enable JavaScript and cookies". Seen on the JSON `/api/v2/catalog/items` without a session cookie, never on the HTML pages so far. Back off for hours; check `curl -s -o /dev/null -w '%{http_code}' -A 'Mozilla/5.0' 'https://www.vinted.pt/catalog?search_text=x'`.
- "page data changed" names the missing key (`items`, `catalogTree`, `dynamicFilters`, `plugins`, `pricingServices`): re-record fixtures with `python3 dev/record_fixtures.py`, fix the parser in `src/api/`.
- Brands need the anonymous cookie the home page sets (`access_token_web`, cached an hour in `session-<site>.json`); 401 → one refresh. No cookie set → exit 3.
- Dead routes (2026-10-23): `/api/v2/catalog/items` (404 for web sessions), `/api/v2/svc-filters/*` (404). Do not go back to them.
- Fallback if pages get walled for good: drive the site in a real browser with `playwright-cli`. Not built.

## Not covered

- Messaging sellers, offers, buying, account actions: no public API; out of scope by design.
- Seller location, item views, price history: not on the pages.
