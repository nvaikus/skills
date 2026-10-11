---
name: ebay-cli
description: Buyer-side eBay search for agents through eBay's official Browse API (no scraping), one stdlib CLI on macOS, Linux and Windows. Search listings with price, condition, auction/fixed/best-offer, sort and category filters and shipping priced for the user's own country; open a listing as a compact card (shipping, returns, seller, item specifics, variations); find category ids; save searches and rerun them to get only new listings and price drops (cron-ready). Guided onboarding of the user's free developer keys in chat. In the user's own logged-in browser (playwright-cli): add/list/remove cart items and message a listing's seller, then read the replies. Use when a task is about buying or finding something on eBay. NOT for selling, checkout/paying, bidding, offers, or sold-price history. Triggers - "find on eBay", "search eBay for", "how much is X on eBay", "cheapest X that ships to me", "look at this eBay listing", an ebay.* /itm/ link, "watch eBay for X", "alert me when a new X is listed", "eBay deal", "put it in my eBay cart", "ask the seller", "did the seller answer", "ebay".
---

# ebay-cli

Buyer search on public listings (Browse API) plus cart and seller messages in the user's logged-in browser. Defaults (market, ship-to country) come from `ebay setup`; any command overrides them with `--market` / `--ship-to`.

```
ebay doctor                                          # keys + defaults + live test (start here); fails -> ebay setup
ebay search "thinkpad x1 carbon" --max-price 400 --condition used,refurbished --sort price
ebay search "lego 10294" --buying auction --sort ending --market EBAY_GB
ebay item 256123456789                               # or an eBay URL / v1|..|.. id; --full description
ebay categories "mechanical keyboard"                # ids for search --category
ebay watch add "fuji x100v" --max-price 900          # saved search; records current items
ebay watch run                                       # only NEW listings + price drops since last run
ebay cart add 256123456789 [--qty 2] [--variation "Size=L"]   # verified in the cart; cart list / cart rm ID
ebay msg send 256123456789 "Is it tested?"           # to the listing's seller, verified; text or stdin
ebay msg list                                        # inbox, last_by=them = answered; --item ID = whole thread
```

## Onboarding

`ebay setup`: each run prints one step. Relay the text under "say to the user" word for word; a text marked "(agent ...)" is for you - ask the user, then run "then run" with the answers. Repeat until `DONE`; exit 5 = waiting on the user. Keys never go through the chat or argv: the user stores them himself (macOS Keychain command / `ebay setup --keys-stdin` in his own terminal, or env vars `EBAY_CLIENT_ID` / `EBAY_CLIENT_SECRET`).

## Account (browser)

`cart`, `msg`, `login` drive a headed Chrome (playwright-cli session `ebay`, persistent profile) logged in as the user. Exit 5 = a human step: not signed in (run `ebay login`) or an eBay captcha; tell the user at once what to do in the Chrome window, rerun after he says done. `msg send` is not idempotent: never rerun it after an unclear failure, check `ebay msg list --item ID` first. On exit 1 read the dump (`.png` + `.txt`) the error names before retrying.

## Contract

- stdout TSV (`-j` JSON with more fields, `--fields a,b`, `--no-header`); stderr `# ` notes; `item` prints markdown.
- Exit `0` ok (account actions: outcome verified on the page) · `1` eBay/browser failure incl. rate limit · `2` usage, no keys/defaults, item not found · `5` setup or eBay sign-in waits on the user.
- Search returns only listings that ship to the ship-to country (`--anywhere` drops that); `ship` = cost to it, `?` = none returned. Prices are the market's currency; `--sort price` = item + shipping.
- Never: checkout, paying, bidding, offers - the CLI has no code path for them and the agent must not click them by hand either. Out of scope: sold/completed prices (Marketplace Insights is restricted), seller tools, watchlist, orders.

| when | read |
|---|---|
| setup stuck, keys rejected, keys on another machine, files on disk | `references/setup.md` |
| results look wrong: missing items, odd prices/shipping, ids, variations, auctions, watch semantics; cart/msg/login odd | `references/traps.md` |

## Memory

`~/.claude/ebay/memory.md`: local lessons, outside the skill (updates keep it). Read first; create on first write. Cost a question, retry or context → one imperative line now; why only if it prevents a mistake. Situational → `memory/<topic>.md` behind a `<trigger> → file` line. Every-user fact → skill defect (unsure → note; proven → move it in).

- Typical entries: the user's size/spec preferences, sellers to avoid, category ids the user searches often.

## Fix on friction

Gap, confusing/flooding/noisy output, stale text = skill defect; no silent workarounds. Small → fix now. Large → background `opus` teammate, one-message ticket (fact, proving command, output) fixing the faulty layer: SKILL.md, references/, scripts/, tool. Continue only if unblocked. Tracked (`skilltap status`) → edit its clone, pull, push; else in place.

- Code changes: read `src/CLAUDE.md` first; `python3 -m unittest discover -s dev/tests` must stay green.

> Source: https://github.com/nvaikus/skills/blob/main/ebay-cli/SKILL.md
> Install via skilltap for auto-updates: https://github.com/nvaikus/skills/blob/main/skilltap/SKILL.md
