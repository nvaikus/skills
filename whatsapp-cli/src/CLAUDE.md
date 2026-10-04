# wa-cli — developer brief

Keep this file one screen. Entry `wa-cli.py` → `src/main.py:main`; re-execs under `~/.wa-cli/venv` when it exists.

## Invariants — never break

- Python 3.10+ at runtime (neonize); `--help`, `accounts` and the tests run on any python3 without neonize. stdlib only, except neonize (+ its segno for the QR), imported lazily and only in `core/wa.py` and `api/auth.py`.
- A command never touches neonize or protos and never prints: it calls `api/`, hands rows to `ctx.write`. `-j` / `--fields` / `--no-header` come free from `main`.
- stdout = data only; stderr = `# ` notes and `wa-cli: <error>`. BrokenPipe → exit 0. neonize logs go to `~/.wa-cli/logs/<account>.log` (root logger claimed before its import); while connected, fds 1/2 point there too (`wa.Quiet`: the Go lib prints straight to them) and sys.stdout/stderr sit on dups of the real fds — so resolve `sys.stdout`/`sys.stderr` at write time, never capture them at import.
- Exit: 0 ok · 1 WhatsApp/runtime (rate limit, ban, network) · 2 usage/config/not logged in/not found/ambiguous · 3 refused (nothing sent) · 130. Raise `CliError`/`UsageError`/`Refused`; never branch on message text outside `wa.translate`.
- Nothing received may be lost: the server acks a delivered message and never resends it. Every connect drains into the store (`api/sync.drain`); events still queued at disconnect go through `sync.absorb` in `ctx.close`.
- One connection per account (flock in `core/wa.py`): two would replace each other's stream.
- Ban hygiene is product behavior: no bulk/loop paths, no retry on rate limit or ban, `join` looks at the link before joining. `send`: no preview by design (same as tg-cli); the rail is exit 2 on an ambiguous/unknown target and a WhatsApp-registration check for unseen phones. `WRITE = True` marks send/join/login/logout.
- Text goes out verbatim as `Message(conversation=…)` — neonize's `send_message(str)` would parse `@digits` as mentions.

## Layers

| file | owns |
|---|---|
| `main.py` | argv, global flags, exit codes, streams, `top_help` |
| `registry.py` | name → (module, help); area = module path segment |
| `context.py` | `ctx.session()` (connect + drain), `ctx.store()`, `ctx.synced_store()` (`--offline`), `close` (absorb) |
| `core/wa.py` | neonize import/logging, lock, `connect` → `Session` (thread + event queue, `events()` drain loop over `DATA` kinds, requests returning dicts), `translate` |
| `core/store.py` | SQLite schema (chats, contacts, messages + FTS5 via triggers), upserts, queries — no protos |
| `core/` other | output, config, errors, timeparse — no domain nouns |
| `api/normalize.py` | proto → rows, duck-typed (`HasField`/getattr): content kinds, edits/revokes, history sync, channel posts |
| `api/sync.py` | the only store writer: `apply`/`drain`/`absorb`, hourly contacts+groups refresh. `sync --follow` = connect once + `apply` in a loop |
| `api/peers.py` | display names, chat/contact rows, `find`, `resolve` (the ref grammar: me, +phone, jid, name) |
| `api/messages.py`, `groups.py`, `channels.py` | rows and actions per noun |
| `api/auth.py` | QR / pairing-code link flow, `me_row` |
| `commands/<area>/<cmd>.py` | argparse + orchestration, one command per file, <~150 lines |

## Add a command

1. `registry.COMMANDS["verb-noun"] = ("src.commands.<area>.<verb_noun>", "one-line help")`.
2. Module: `FIELDS`, `EPILOG` (2–4 examples + traps), `add_args(p)`, `run(ctx, args)`; `WRITE = True` if it changes anything on WhatsApp; store reads take `--offline`. Never declare `-j/--fields/--no-header/--account`.
3. Tests in `dev/tests/test_cli.py` (`FakeSession` replaces `wa.connect`; `P` fakes protos).

## Route discovery

neonize client methods (`neonize/client.py` in the venv) first; their protos: `neonize/proto/` (`Neonize_pb2`, `waE2E`, `waHistorySync`). Go side = whatsmeow (pkg.go.dev/go.mau.fi/whatsmeow). Not available there (checked 0.5.2): channel directory search, newsletter post timestamps (not in the raw reply either), a follow flag in newsletter info (`ViewerMeta.Role` reads subscriber when not following - use `get_subscribed_newletters`), post views for non-admins (ViewsCount 0), group size in an invite-link preview (partial participant list).

## Test

- `python3 -m unittest discover -s dev/tests` — mocked, no network, no neonize.
- Live: reads on any account; `send` only to `me`. Never `logout` or `join` with a real account in tests.
