# tg-cli — developer brief

Keep this file one screen. Entry `tg-cli.py` → `src/main.py:main`; re-execs under `~/.tg-cli/venv` when it exists.

## Invariants — never break

- Python 3.9+. stdlib only, except Telethon + qrcode, imported lazily and only in `core/tg.py` and `api/auth.py` (house-rule exception: MTProto cannot be done in stdlib; agreed 2026-09-30). `--help` and `accounts` work without them.
- A command never talks to Telethon directly and never prints: it calls `api/`, hands rows to `ctx.write`. `-j` / `--fields` / `--no-header` come free from `main`.
- stdout = data only; stderr = `# ` notes and `tg-cli: <error>`. BrokenPipe → exit 0.
- Exit: 0 ok · 1 Telegram/runtime · 2 usage/config/not logged in/not found/ambiguous · 3 refused (nothing sent) · 4 needs Premium · 130. Raise `CliError`/`UsageError`/`Refused`/`Cannot`; never branch on message text.
- Credentials never in argv: API keys from env/config, codes and 2FA from a tty prompt.
- `send` has no preview/--force by user decision (2026-09-30): "if sent, then sent". The rail that stays: an ambiguous or unknown target is exit 2 and nothing is sent. `WRITE = True` marks it (and login/logout) so tests never hit them live.
- `--public` never passes `allow_paid_stars`; out of free slots is exit 3.
- Text goes out verbatim (`parse_mode=None`); markdown only on `--markdown` (agent text full of `_` and `*` would be mangled by the md parser).

## Layers

| file | owns |
|---|---|
| `main.py` | argv, global flags, exit codes, streams, `top_help` |
| `registry.py` | name → (module, help); area = module path segment |
| `context.py` | `ctx.client()` (lazy connect), `ctx.write`, `ctx.note` |
| `core/tg.py` | Telethon import/connect, raw TL requests, `translate` (Telethon error → CliError) |
| `core/` other | output, config, errors, timeparse — no domain nouns |
| `api/peers.py` | entity kind/name/marked id/link, dialogs, `find`, `resolve` (the ref grammar) |
| `api/messages.py` | message rows, history, search, public search, send |
| `api/auth.py` | QR/phone/2FA flows, `me_row` |
| `commands/<area>/<cmd>.py` | argparse + orchestration, one command per file, <~150 lines |

Entities are duck-typed by Telethon class name (`User`/`Chat`/`Channel`) so tests need no Telethon.

## Add a command

1. `registry.COMMANDS["verb-noun"] = ("src.commands.<area>.<verb_noun>", "one-line help")`.
2. Module: `FIELDS`, `EPILOG` (2–4 examples + this command's traps), `add_args(p)`, `run(ctx, args)`; `WRITE = True` if it changes anything on Telegram. Never declare `-j/--fields/--no-header/--account`.
3. Tests in `dev/tests/test_cli.py` (`FakeClient`, patched `core.tg` raw calls).

## Route discovery

Telethon high-level (`iter_messages`, `iter_dialogs`, `get_entity`, `send_message`) first; raw TL goes into `core/tg.py`. Method/param truth: core.telegram.org/method/<name>; installed layer: `python -c "from telethon.tl.alltlobjects import LAYER; print(LAYER)"`. `iter_messages(None, search=…)` = `messages.searchGlobal`.

## Test

- `python3 -m unittest discover -s dev/tests` — mocked, no network, no Telethon.
- Live: reads on any account; `send` only to `me` (Saved Messages). Never `logout` a real session in tests.
- Per command: `-j` parses, `--fields` narrows both formats, `--no-header`, `| head -1` exits 0, every exit code it can produce.

## Friction rule

AI friction is a defect — confusing output, noisy errors, a missing capability: fix it in this repo, do not work around it.
