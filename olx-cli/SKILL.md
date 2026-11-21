---
name: olx-cli
description: 'Buyer-side OLX search and price monitoring via OLX''s unofficial frontend JSON API, one stdlib CLI. olx.pt by default, other countries (pl, ro, bg, ua, kz, uz) via --site. Search listings with price, category, region/city + radius, condition, seller-type and sort filters; open a listing as a compact card; find category and place ids; save searches and rerun them on a schedule for only new listings and price drops, optional Telegram alert via claude-tg. Tracks endpoint breakage. In the user''s logged-in Chrome (playwright-cli): sign in once, message a seller via OLX chat, read replies. Use when buying or finding something on OLX, or talking to an OLX seller. NOT for selling, posting ads, buying or paying. Triggers - "find on OLX", "search OLX for", "olx.pt", "how much is X on OLX", an olx.* /d/anuncio/ or /d/oferta/ link, "watch OLX for X", "alert me when a new X appears on OLX", "OLX price drop", "ask the seller on OLX", "write to the OLX seller", "did the seller reply", "OLX chat", "olx".'
---

# olx-cli

Buyer search on OLX's unofficial `/api/v1/offers/` (no keys, no login), plus seller chat in the user's logged-in browser. Default site from `~/.claude/olx/config.json` (`site`, default `pt`) or `OLX_SITE`; every command takes `--site CC`.

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
olx login                                             # signed in? else opens OLX sign-in, exit 5
olx msg send 674669746 "Ainda está disponível?"       # to the listing's seller, verified; text or stdin
olx msg list [--id ID | --conversation CID]           # inbox (last_by=them = answered) or one thread
```

## Account (browser)

`login`, `msg` drive a plain headed Chrome on its own profile (playwright-cli session `olx`, attached over CDP). Exit 5 = a human step: not signed in (run `olx login`) or a captcha; tell the user at once (on a headless server the error carries a remote-view link: send it), rerun after he says done. `msg send` is not idempotent and does not retry: after exit 1 or any unclear failure the message may already be out, never rerun it before `olx msg list --id ID`. On exit 1 read the dump (`.png` + `.txt`) the error names before retrying. Setup, config keys, selectors: `references/account.md`.

## Contract

- stdout TSV (`-j` JSON with more fields: price_value, price_kind, seller, photos, created/refreshed..., `--fields a,b`, `--no-header`); stderr `# ` notes; `show` prints markdown; `photos` prints n, path, bytes (default dir `./olx-<id>`).
- Exit `0` ok (account actions: outcome verified on the page) · `1` OLX/network/browser failure · `2` usage, unknown name, listing not found, chat disabled · `3` OLX broke: blocked (403/captcha) or JSON changed → read `references/traps.md` "When it breaks" · `5` sign-in or captcha waits on the user.
- Price column: number in the site currency, `N neg` = negotiable, `swap` / `free` / `ask` (no number), `-` none.
- OLX's query is fuzzy (matches word forms and unrelated categories): add `--category` and/or `--must` when results drift.
- Never: posting ads, buying, paying, OLX delivery checkout, offers — no code path for them, and the agent must not click them by hand either.

## Scheduling

- `olx watch run --notify` is cron-ready: no prompts, empty stdout when nothing changed, one Telegram message per run with hits and failures (`claude-tg notify --topic olx`; `--topic` / config `notify_topic` override).
- Schedule it as a clockmaster job (e.g. every 2-6 h; OLX is polite-rate limited at 1 req/s). Register topic `olx` in claude-tg `notify_topics` first if it is not there.

| when | read |
|---|---|
| exit 3, odd results (missing listings, order, prices, filters ignored), watch semantics, fallback | `references/traps.md` |
| login / msg: setup, headless host, exit 5 loops, odd thread or inbox rows, selector changes | `references/account.md` |

## Memory

`~/.claude/olx/memory.md`: local lessons, outside the skill (updates keep it). Read first; create on first write. Cost a question, retry or context → one imperative line now; why only if it prevents a mistake. Situational → `memory/<topic>.md` behind a `<trigger> → file` line. Every-user fact → skill defect (unsure → note; proven → move it in).

- Typical entries: the user's region/city, category ids searched often, words to `--must` for a recurring hunt.

## Fix on friction

Gap, confusing/flooding/noisy output, stale text = skill defect; no silent workarounds. Small → fix now. Large → background `opus` teammate, one-message ticket (fact, proving command, output) fixing the faulty layer: SKILL.md, references/, scripts/, tool. Continue only if unblocked. Tracked (`skilltap status`) → edit its clone, pull, push; else in place.

- Code changes: read `src/CLAUDE.md` first; `python3 -m unittest discover -s dev/tests` must stay green.

> Source: https://github.com/nvaikus/skills/blob/main/olx-cli/SKILL.md
> Install via skilltap for auto-updates: https://github.com/nvaikus/skills/blob/main/skilltap/SKILL.md
