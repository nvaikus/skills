# Traps (search, item, watch, account)

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

## Account (cart, msg, login)
- Needs `playwright-cli` (npm `@playwright/cli`) and Chrome. Session `ebay` (config `browser_session` / env `EBAY_BROWSER_SESSION`); a separate session = separate profile = separate login.
- One action at a time per session: two parallel `ebay cart`/`msg` calls drive the same tab.
- Exit 5 "captcha": eBay challenges after bursts of automated page loads; the user solves it in the Chrome window. Space out calls; don't loop.
- Signed-in check = cookie `ebay` with `sin=in`; an expired login that keeps the cookie shows up as a redirect to `signin.*` - also exit 5.
- Cart `price`/`shipping` are display strings in the site's language and the listing's currency; `seller` is the store label, not the user id.
- `cart add` on a listing already in the cart (no `--variation`) does nothing. Multi-variation listing needs `--variation` (id from `ebay item`, or aspects `Size=L,Colour=Black` matched via the Browse API = needs keys).
- `cart rm ID` removes every line of that id, all variations.
- Seller user id comes from the Browse API (listing pages show store slugs, not ids); without keys the CLI clicks "contact seller" to read it. `--seller` skips both.
- Message times are the site's local strings (`Heute 18:41`, `Gestern`); `from` = `me` or the seller id. A seller reply shows in `msg list` as `last_by=them`. eBay auto-translates the seller's messages into the site language: `msg list --item` text = translation, `-j` field `original` = what the seller wrote.
- `msg send` does not retry. After exit 1 the message may still have gone out: `ebay msg list --item ID` before resending.
- Failures leave `~/.claude/ebay/browser/dumps/<step>-<ts>.png` + `.txt` (URL, title, ARIA snapshot).
