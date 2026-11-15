# Traps (search, item, watch, account)

## Search
- One market per call: `EBAY_DE` lists sellers worldwide who offer delivery there, but not every listing of other sites. Missing a known item → retry with its own `--market`.
- `ship` comes from the ship-to context: calculated-rate listings may need `--zip` (or config `zip`); `?` = eBay returned no option for that country even though the filter passed - check `ebay item`.
- Price filter uses the market's currency (`EBAY_GB` = GBP); a listing in another currency is converted by eBay, `-j` keeps `currency`.
- Inside the EU (e.g. `EBAY_DE` → PT) no customs; from GB/US expect import VAT + fees not shown in `ship` (item card shows `import charges` when eBay knows them).
- Max 200 rows per call, 10,000 per query in total; no paging flag - narrow the query.
- `--condition` names map to id groups (used = 2990/3000/3010/4000-6000, refurbished = 2000-2030/2500, parts = 7000); raw ids also work. Not every category uses every id.
- Multi-variation listing (`buy` ends in `var`, price `~`): the summary carries ONE variation eBay picks per call (ship-to and query sway it), so the same id shows different prices across searches; `ebay item ID` = cheapest + all. `watch` reports a drop only for the same variation.
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
- Needs `playwright-cli` (npm `@playwright/cli`) and Chrome. The CLI starts a plain Chrome (`--user-data-dir=~/.claude/ebay/browser/profiles/<session> --remote-debugging-port=9336`) and attaches session `ebay` over CDP (config `browser_session` / env `EBAY_BROWSER_SESSION`, `browser_port` / env `EBAY_BROWSER_PORT`, `browser_chrome`). A separate session = separate profile = separate login. The first start copies the old `playwright-cli open --persistent` profile (`ud-<session>-chrome`). A Chrome of another profile on the port → exit 1, never driven.
- eBay's sign-in cookies (`s`, `ebay`, `ds1`, `ds2`) are session-only unless "Stay signed in" is ticked: every Chrome restart signs out. Keep the Chrome running (below) and tick the box when signing in.
- Bot-run headless host (`claude -p` per message kills the process tree): config `browser_launch_prefix` `["systemd-run", "--user", "--unit=ebay-browser-{ts}", "--setenv=DISPLAY={display}", "--setenv=PATH={path}", "--working-directory={cwd}"]` puts Chrome in its own unit. Stop: `systemctl --user stop 'ebay-browser-*'`.
- Keep-alive: schedule `ebay login --keepalive` every few hours (clockmaster): loads the site in a fresh tab and closes it, the user's tab stays; another `ebay` command running → skipped, exit 0; signed out → exit 5 (notify the user). Commands share a lock: a second one waits up to 300 s.
- Headless Linux server (no desktop): config `browser_display` (e.g. `":99"`) = an always-on Xvfb display used when env has no `DISPLAY`; `browser_view_url` = the user's remote view of it (noVNC link, tailnet-only). With the URL set, exit-5 texts carry it: send the user that link, wait for "done", rerun. Never headless Chrome (captcha wall), never copy a profile from another machine (eBay sees a new device anyway).
- Headless Linux host: install `xdotool` (`apt install xdotool`). Sessions share one Xvfb display with no window manager, so another session's browser can bury this one; before every exit 5 the CLI raises its own window (`xdotool windowraise`). Missing xdotool → a `# ` stderr note, the command still works.
- Exit 5 "captcha": eBay challenges after bursts of automated page loads; the user solves it in the Chrome window. Space out calls; don't loop.
- Signed-in check = cookie `ebay` with `sin=in`; an expired login that keeps the cookie shows up as a redirect to `signin.*` - also exit 5.
- Cart `price`/`shipping` are display strings in the site's language and the listing's currency; `seller` is the store label, not the user id.
- Multi-variation listing needs `--variation` (id from `ebay item`, or aspects `Size=L,Colour=Black` matched via the Browse API = needs keys).
- Seller user id comes from the Browse API (listing pages show store slugs, not ids); without keys the CLI clicks "contact seller" to read it. `--seller` skips both.
- Failures leave `~/.claude/ebay/browser/dumps/<step>-<ts>.png` + `.txt` (URL, title, ARIA snapshot).
