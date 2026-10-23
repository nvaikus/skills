---
name: vinted-cli
description: 'Buyer-side Vinted search and price monitoring for agents through Vinted''s own web pages (unofficial, no login), one stdlib CLI. vinted.pt by default, any Vinted country (fr, es, de, it, pl, nl, be, co.uk ...) via --site. Search items with price, category, brand, size, condition, color and sort filters; open an item as a compact card (id or URL) with the price including the buyer-protection fee, seller rating and photo links; look up category, brand, size, condition and color ids; save searches and rerun them on a schedule to get only new items and price drops, with an optional Telegram alert via claude-tg. Records how often the unofficial source breaks. Use when a task is about buying or finding something on Vinted. NOT for selling, messaging sellers, buying or Vinted account actions. Triggers - "find on Vinted", "search Vinted for", "vinted.pt", "how much is X on Vinted", a vinted.* /items/ link, "watch Vinted for X", "alert me when a new X appears on Vinted", "Vinted price drop", "vinted".'
---

# vinted-cli

Read-only buyer search on Vinted's server-rendered pages (no keys, no login). Default site from `~/.claude/vinted/config.json` (`site`, default `pt`) or `VINTED_SITE`; every command takes `--site TLD`.

```
vinted doctor                                          # live check + breakage stats (start here)
vinted search "nike air max" --max-price 40 --size 776 --sort price
vinted search levis 501 --brand levis --condition new-tags,very-good --color blue
vinted search "barbour" --site co.uk --must barbour --sort newest   # --must = client-side title filter
vinted show 7123456789                                 # or a Vinted URL; --full = every photo + description
vinted categories --grep trainers                      # ids for --category (names / slugs work too)
vinted brands "north face"                             # ids for --brand (names work too)
vinted sizes --category 1242                           # ids for --size (per category; first call ~10 s)
vinted conditions · vinted colors                      # fixed ids, every site
vinted watch add "patagonia fleece" --max-price 50 --category 1206   # saved search; records current items
vinted watch run [--notify]                            # only NEW items + price drops since last run
```

## Contract

- stdout TSV (`-j` JSON with more fields: fee, was, promoted, favourites, seller_id, photo; `--fields a,b`, `--no-header`); stderr `# ` notes; `show` prints markdown (`-j` = flat dict).
- Exit `0` ok · `1` Vinted/network failure · `2` usage, unknown name, item not found · `3` Vinted broke: blocked (Cloudflare) or page data changed → read `references/traps.md` "When it breaks".
- Columns: `price` = item price (after a seller discount); `total` = price + buyer-protection fee, shipping extra; `brand`, `size`, `cond` as the site words them.
- Vinted's query is fuzzy: add `--category`, `--brand` and/or `--must` when results drift. Names are in the site's language.
- Never: selling, messaging sellers, buying, offers, favourites — no code path for them.

## Scheduling

- `vinted watch run --notify` is cron-ready: no prompts, empty stdout when nothing changed, one Telegram message per run with hits and failures (`claude-tg notify --topic vinted`; `--topic` / config `notify_topic` override).
- Schedule it as a clockmaster job (e.g. every 2-6 h; requests are paced 1.5 s apart). Register topic `vinted` in claude-tg `notify_topics` first if it is not there.

| when | read |
|---|---|
| exit 3, odd results (location, totals, filters ignored, ids), watch semantics, messaging sellers, fallback | `references/traps.md` |

## Memory

`~/.claude/vinted/memory.md`: local lessons, outside the skill (updates keep it). Read first; create on first write. Cost a question, retry or context → one imperative line now; why only if it prevents a mistake. Situational → `memory/<topic>.md` behind a `<trigger> → file` line. Every-user fact → skill defect (unsure → note; proven → move it in).

- Typical entries: the user's sizes (ids per category), favourite brands, site, words to `--must` for a recurring hunt.

## Fix on friction

Gap, confusing/flooding/noisy output, stale text = skill defect; no silent workarounds. Small → fix now. Large → background `opus` teammate, one-message ticket (fact, proving command, output) fixing the faulty layer: SKILL.md, references/, scripts/, tool. Continue only if unblocked. Tracked (`skilltap status`) → edit its clone, pull, push; else in place.

- Code changes: read `src/CLAUDE.md` first; `python3 -m unittest discover -s dev/tests` must stay green.

> Source: https://github.com/nvaikus/skills/blob/main/vinted-cli/SKILL.md
