---
name: olx-cli
description: 'Buyer-side OLX search and price monitoring for agents through OLX''s unofficial frontend JSON API, one stdlib CLI. olx.pt by default, other OLX countries (pl, ro, bg, ua, kz, uz) via --site. Search listings with price, category, region/city + radius, condition, seller-type and sort filters; open a listing as a compact card (id or URL); find category and place ids; save searches and rerun them on a schedule to get only new listings and price drops, with an optional Telegram alert via claude-tg. Records how often the unofficial endpoint breaks. Use when a task is about buying or finding something on OLX. NOT for selling, messaging sellers, buying or OLX account actions. Triggers - "find on OLX", "search OLX for", "olx.pt", "how much is X on OLX", an olx.* /d/anuncio/ or /d/oferta/ link, "watch OLX for X", "alert me when a new X appears on OLX", "OLX price drop", "olx".'
---

# olx-cli

Read-only buyer search on OLX's unofficial `/api/v1/offers/` (no keys, no login). Default site from `~/.claude/olx/config.json` (`site`, default `pt`) or `OLX_SITE`; every command takes `--site CC`.

```
olx doctor                                            # live check + breakage stats (start here)
olx search "bicicleta gravel" --max-price 600 --region Lisboa --sort price
olx search "frigorifico" --city Ericeira --distance 20 --condition used --seller private
olx search "rower" --site pl --must rower,gravel --sort newest    # --must = client-side title filter
olx show 674669746                                    # or an OLX URL; --full description
olx photos 674669746 [-o DIR] [--max N] [--sheet]     # download all photos, prints paths; --sheet = one grid JPEG (ffmpeg)
olx categories bicicleta                              # ids for --category (names work too)
olx places ericeira                                   # city ids; --regions for regions
olx watch add "macbook air m2" --max-price 700 --must macbook   # saved search; records current listings
olx watch run [--notify]                              # only NEW listings + price drops since last run
```

## Contract

- stdout TSV (`-j` JSON with more fields: price_value, price_kind, seller, photos, created/refreshed..., `--fields a,b`, `--no-header`); stderr `# ` notes; `show` prints markdown; `photos` prints n, path, bytes (default dir `./olx-<id>`).
- Exit `0` ok · `1` OLX/network failure · `2` usage, unknown name, listing not found · `3` OLX broke: blocked (403/captcha) or JSON changed → read `references/traps.md` "When it breaks".
- Price column: number in the site currency, `N neg` = negotiable, `swap` / `free` / `ask` (no number), `-` none.
- OLX's query is fuzzy (matches word forms and unrelated categories): add `--category` and/or `--must` when results drift.
- Never: posting, messaging sellers, buying — no code path for them.

## Scheduling

- `olx watch run --notify` is cron-ready: no prompts, empty stdout when nothing changed, one Telegram message per run with hits and failures (`claude-tg notify --topic olx`; `--topic` / config `notify_topic` override).
- Schedule it as a clockmaster job (e.g. every 2-6 h; OLX is polite-rate limited at 1 req/s). Register topic `olx` in claude-tg `notify_topics` first if it is not there.

| when | read |
|---|---|
| exit 3, odd results (missing listings, order, prices, filters ignored), watch semantics, messaging sellers, fallback | `references/traps.md` |

## Memory

`~/.claude/olx/memory.md`: local lessons, outside the skill (updates keep it). Read first; create on first write. Cost a question, retry or context → one imperative line now; why only if it prevents a mistake. Situational → `memory/<topic>.md` behind a `<trigger> → file` line. Every-user fact → skill defect (unsure → note; proven → move it in).

- Typical entries: the user's region/city, category ids searched often, words to `--must` for a recurring hunt.

## Fix on friction

Gap, confusing/flooding/noisy output, stale text = skill defect; no silent workarounds. Small → fix now. Large → background `opus` teammate, one-message ticket (fact, proving command, output) fixing the faulty layer: SKILL.md, references/, scripts/, tool. Continue only if unblocked. Tracked (`skilltap status`) → edit its clone, pull, push; else in place.

- Code changes: read `src/CLAUDE.md` first; `python3 -m unittest discover -s dev/tests` must stay green.

> Source: https://github.com/nvaikus/skills/blob/main/olx-cli/SKILL.md
