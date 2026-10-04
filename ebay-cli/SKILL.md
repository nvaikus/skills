---
name: ebay-cli
description: Buyer-side eBay search for agents through eBay's official Browse API (no scraping), one stdlib CLI on macOS, Linux and Windows. Search listings with price, condition, auction/fixed/best-offer, sort and category filters and shipping priced for the user's own country; open a listing as a compact card (shipping, returns, seller, item specifics, variations); find category ids; save searches and rerun them to get only new listings and price drops (cron-ready). Guided onboarding of the user's free developer keys in chat. Use when a task is about buying or finding something on eBay - "find on eBay", "search eBay for", "how much is X on eBay", "cheapest X that ships to me", "look at this eBay listing", an ebay.* /itm/ link, "watch eBay for X", "alert me when a new X is listed", "eBay deal", "ebay". NOT for selling, bidding/buying, or sold-price history (eBay keeps those APIs partner-only).
---

# ebay-cli

Read-only buyer search on public listings. Defaults (market, ship-to country) come from `ebay setup`; any command overrides them with `--market` / `--ship-to`.

```
ebay doctor                                          # keys + defaults + live test (start here); fails -> ebay setup
ebay search "thinkpad x1 carbon" --max-price 400 --condition used,refurbished --sort price
ebay search "lego 10294" --buying auction --sort ending --market EBAY_GB
ebay item 256123456789                               # or an eBay URL / v1|..|.. id; --full description
ebay categories "mechanical keyboard"                # ids for search --category
ebay watch add "fuji x100v" --max-price 900          # saved search; records current items
ebay watch run                                       # only NEW listings + price drops since last run
```

## Onboarding

`ebay setup`: each run prints one step. Relay the text under "say to the user" word for word; a text marked "(agent ...)" is for you - ask the user, then run "then run" with the answers. Repeat until `DONE`; exit 5 = waiting on the user. Keys never go through the chat or argv: the user stores them himself (macOS Keychain command / `ebay setup --keys-stdin` in his own terminal).

## Contract

- stdout TSV (`-j` JSON with more fields, `--fields a,b`, `--no-header`); stderr `# ` notes; `item` prints markdown.
- Exit `0` ok · `1` eBay failure incl. rate limit · `2` usage, no keys/defaults, item not found · `5` setup waits on the user.
- Search returns only listings that ship to the ship-to country (`--anywhere` drops that); `ship` = cost to it, `?` = none returned. Prices are the market's currency; `--sort price` = item + shipping.
- Out of scope: bidding, buying, offers (Buy Offer/Order APIs are partner-only), sold/completed prices (Marketplace Insights is restricted), seller APIs, the user's own eBay account (watchlist, orders).

| when | read |
|---|---|
| setup stuck, keys rejected, keys on another machine, files on disk | `references/setup.md` |
| results look wrong: missing items, odd prices/shipping, ids, variations, auctions, watch semantics | `references/traps.md` |

## Memory

`~/.claude/ebay/memory.md`: local lessons, outside the skill (updates keep it). Read first; create on first write. Cost a question, retry or context → one imperative line now; why only if it prevents a mistake. Situational → `memory/<topic>.md` behind a `<trigger> → file` line. Every-user fact → skill defect (unsure → note; proven → move it in).

- Typical entries: the user's size/spec preferences, sellers to avoid, category ids the user searches often.

## Fix on friction

Gap, confusing/flooding/noisy output, stale text = skill defect; no silent workarounds. Small → fix now. Large → background `opus` teammate, one-message ticket (fact, proving command, output) fixing the faulty layer: SKILL.md, references/, scripts/, tool. Continue only if unblocked. Tracked (`skilltap status`) → edit its clone, pull, push; else in place.

- Code changes: read `src/CLAUDE.md` first; `python3 -m unittest discover -s dev/tests` must stay green.

> Source: https://github.com/nvaikus/skills/blob/main/ebay-cli/SKILL.md
> Install via skilltap for auto-updates: https://github.com/nvaikus/skills/blob/main/skilltap/SKILL.md
