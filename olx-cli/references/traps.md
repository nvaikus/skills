# olx-cli traps (live-checked 2026-10-21)

## Results

- Query is fuzzy: word forms, other categories, description hits. `--must w1,w2` keeps titles containing every word (prefix, accents ignored) and scans only `--limit` organic rows, so it can return fewer.
- `--sort newest` = last refresh (`created_at:desc` really orders by `last_refresh_time`): old listings bumped by the seller come first. `show` gives posted vs refreshed.
- `--sort price` puts listings without a numeric price (swap/free/ask) first.
- Default sort = OLX relevance. Promoted ads (3 rows OLX prepends, ignoring sort) are dropped; stderr notes how many.
- Hard window: offset ≤ 1000, page ≤ 50 rows. `total` notes use `visible_total_count`; anything past 1000 is unreachable — narrow the filters.
- A filter value OLX does not know (e.g. `--condition` in a category without a state param) silently returns 0 rows, not an error. Bad category/sort ids → HTTP 400 (exit 1) with the validation text.
- `--city` takes the first autocomplete hit (stderr says which); `--distance` needs `--city`; `--region` is ignored when `--city` is given. Names resolve per site.
- Prices are the site's currency (EUR pt/bg, PLN, RON, UAH, KZT, UZS). `was` = the old price OLX itself shows after a cut.

## Watches

- Saved with resolved ids + site at add time; run uses newest-first order and the saved `--limit` (default 50).
- `new` = id never seen by this watch; a refreshed old listing is not new. `drop OLD>NEW` only for numeric same-currency prices. Seen state forgets ids unseen for 60 days.
- State: `~/.claude/olx/watch/` (`searches.json`, `seen/<name>.json`, `alerted.json`). Override root: `OLX_ROOT`.
- `--notify` topic `olx` must exist in claude-tg `notify_topics` (not registered by this skill).

## When it breaks (exit 3)

- The endpoint is unofficial: CloudFront / bot walls or schema changes can stop it any day. Every request outcome goes to `~/.claude/olx/health.tsv` (`ts host path ok|blocked|schema|http|network detail`); `olx doctor` shows 30-day counts and the last failure. That file is the experiment's answer to "how often does it break".
- Known trigger: CloudFront 403s a TLS ClientHello with the `post_handshake_auth` extension (Python urllib's default context, `curl --http1.1`). `core/http.tls_context()` turns it off — never revert. A new 403 → compare with `curl -s -o /dev/null -w '%{http_code}' 'https://www.olx.pt/api/v1/offers/?query=x&limit=1'` (HTTP/2): curl ok + CLI blocked = fingerprinting again.
- Schema change → `need()` guards in `api/olx.py` / `offers.py` name the missing field; re-record fixtures from a live response and fix the parser.
- Fallback if the API is walled for good: drive the site in a real browser with `playwright-cli`. Not built.

## Not covered

- Messaging sellers / account actions: the official OLX Partner API (developer.olx.pt, OAuth app per site) covers the user's own adverts and messages but has no search of other people's listings. Future path for "ask the seller", not for search.
- Category names come from the home page's `__PRERENDERED_STATE__` (cached a week in `cache/categories-<site>.json`; `olx categories --refresh`); `/api/v1/categories` is deprecated.
