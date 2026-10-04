# Traps (search, item, watch)

## Search
- One market per call: `EBAY_DE` lists sellers worldwide who offer delivery there, but not every listing of other sites. Missing a known item → retry with its own `--market`.
- `ship` comes from the ship-to context: calculated-rate listings may need `--zip` (or config `zip`); `?` = eBay returned no option for that country even though the filter passed - check `ebay item`.
- Price filter uses the market's currency (`EBAY_GB` = GBP); a listing in another currency is converted by eBay, `-j` keeps `currency`.
- Inside the EU (e.g. `EBAY_DE` → PT) no customs; from GB/US expect import VAT + fees not shown in `ship` (item card shows `import charges` when eBay knows them).
- `price` for auctions = current bid, not the final price; `ends` is UTC.
- Max 200 rows per call, 10,000 per query in total; no paging flag - narrow the query.
- `--condition` names map to id groups (used = 2990/3000/3010/4000-6000, refurbished = 2000-2030/2500, parts = 7000); raw ids also work. Not every category uses every id.
- Query: space = AND, `(a,b)` = OR, `-word` excludes; `*` is refused.

## Item
- `id` column = legacy listing id (the number in eBay URLs). Multi-variation listings (sizes, colours): `item` shows the cheapest variation + all; a single variation needs its `v1|<id>|<variation>` id or the URL with `?var=`.
- Ended or removed listings → exit 2 "not found". `11004` = seller is editing, retry in minutes.
- Description is seller HTML flattened to text and cut at 1500 chars unless `--full`.

## Watch
- `watch add` records current matches at once; only later listings are reported as `new`. `drop` = fixed price lower than last run (same currency); auction bids are never compared.
- Each run looks at the newest `--limit` (default 50) matches only; a broad query with many new listings per run can miss some - narrow it or raise `--limit` (max 200).
- An item unseen for 60 days is forgotten (would be reported `new` again if relisted).
- One API call per watch per run; eBay's default quota is ~5000 Browse calls/day per app (exit 1 "rate limit" when hit).
