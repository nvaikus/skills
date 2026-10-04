# gdrive — developer brief

Keep this file one screen. Entry `gdrive.py` → `src/main.py:main`. Python 3.9+, stdlib only.

## Invariants — never break

- stdlib only, nothing installed on the system. One optional exception: `scripts/console-auto.mjs` (Node + Playwright, onboard `--mode auto`) - it only drives a browser; when missing, onboarding is manual. Python never imports it, `autoconsole` runs it. Mount/sync transfers go through rclone (`api/rclone.py` owns the binary). The only own download code is the indexer's (`google.download`, by id, into a temp dir, original deleted after extraction) - never through a mount (it would fill the Claude-facing VFS cache).
- A command never speaks HTTP and never prints: `api/` does the work, rows go to `ctx.write` / `ctx.grid` / `ctx.text`.
- Transport rail: `core/http.request` refuses non-GET without `allow_mutate=True`; only `api/google.mutate`, `api/auth` (token endpoint) and `api/rclone.rc` pass it. `grep -rn allow_mutate src/commands` stays empty (a test enforces it).
- stdout = data; stderr = `# ` notes and `gdrive: <error>`. Exit 0 · 1 · 2 · 3 rail refusal · 5 onboard waits on the user · 6 wait deadline · 130. Raise `CliError`/`UsageError`/`Refused`/`Deadline`; never branch on message text (`e.status`, `google.reasons(e)`).
- Credentials never in argv: client id/secret from the profile config (imported from a file path), the OAuth redirect URL from a prompt or stdin, the rc password via `RCLONE_RC_*` env of the rclone process.
- Profiles: everything per account resolves through `core/profile` (set once by main from `--profile`/env/default; a mount path may `switch` it). Mount records are global but carry `profile` + `conf`. Config keys are contract.
- Waits bounded: `WAIT = True` modules get `--wait` (200 s default, 230 s cap). Deadline → print the receipt, exit 6, say nothing was undone. Only the service's `index update --unbounded` has no deadline.
- `umount` refuses (exit 3) while the VFS cache has unuploaded writes: rclone drops queued uploads on unmount (live-proven). The per-mount cache dir (`~/.cache/gdrive/<profile>/<id>`) is stable so a remount resumes them.
- Never stat inside a mount to match paths (dead macOS NFS mounts hang uninterruptibly): `mounts._match` compares strings first; liveness reads the kernel mount table.
- No full-document rewrite of a Google Doc. Docs indices are UTF-16 units: every offset through `markdown.u16`.
- Index: `indexer` knows only `api/provider.Provider`; Google specifics live in `gprovider`. what=/ = three-folder layout (`drive.layout_address` ↔ `mounts.everything`); virtual ids `~all`/`~shared-with-me`/`~shared-drives`; sections beyond My Drive only from config `index_sections` (`api/sections.py`). OCR temp copies always carry `appProperties gdriveIndexTemp=1` (the sweep's only selector).

## Layers

| file | owns |
|---|---|
| `main.py` · `registry.py` | argv, `--profile`, `<family> <verb>` dispatch, globals, exit codes · name → (module, help) |
| `core/` | http, output, config (per profile), profile, paths, errors, wait, rails, proc, stdin |
| `api/rclone.py` · `auth.py` · `google.py` | binary · OAuth PKCE + token in the profile's rclone.conf · REST, error → exit code, download |
| `api/drive.py` · `docs.py` · `sheets.py` · `markdown.py` | address grammar · Docs/Sheets ops · Docs JSON ↔ markdown |
| `api/mounts.py` · `mounting.py` · `persist.py` · `rename.py` | records/mechanism/liveness · bring a mount up · mount autostart units · profile rename (all keyed by the name) |
| `api/onboarding.py` · `onboard_say.py` | answers, legacy import, `advance(env)` (12 steps, mode auto/manual); `LiveEnv` = the real checks · every user-facing text |
| `api/autoconsole.py` · `scripts/console-auto.mjs` | auto mode: availability, background job (`onboard --auto-job`) owning all state + loopback catch · browser driver, JSON lines on stdio, steps by role/label text, fail → `{step, msg, screenshot}` |
| `api/provider.py` · `gprovider.py` · `providers.py` | index backend interface · Google Drive impl · profile → provider |
| `api/indexer.py` · `manifest.py` · `extract.py` · `service.py` | sync/reconcile/extract, paths ↔ index · sqlite · file → text · 5-min timer |
| `commands/<area>/<cmd>.py` | argparse + orchestration, one command per file, < ~150 lines |

Shared logic moves down into `api/`, never sideways into another command.

## Add a command

1. `registry.COMMANDS["name"]` or `"family verb"` = `("src.commands.<area>.<file>", "one-line help")`.
2. Module: `FIELDS`, `EPILOG` (2–4 examples + this command's traps), `add_args(p)`, `run(ctx, args)`; `WRITE = True` if it changes Drive or local state; `WAIT = True` if async; `PROFILE = "none"|"create"` when it must run without an existing profile (default `"required"`). Never declare `-j/--fields/--no-header/--wait/--profile`.
3. Tests in `dev/tests/` (import `support` first: one temp env, profile `t`; other profiles are removed after the test). `FakeGoogle` (test_cli) routes by URL; `FakeProvider` (test_index) drives the indexer; `FakeEnv` (test_onboard) replaces every live onboarding check; test_auto runs the job against a fake driver speaking the same JSON lines.

## Route discovery

REST truth: developers.google.com/drive/api/reference/rest/v3 (files, changes, export), /docs/api/reference/rest/v1, /sheets/api/reference/rest/v4. rclone flags: `~/.local/share/gdrive/bin/rclone <cmd> --help`; rc methods: `rclone rc --help`, `vfs/stats` for the cache.

## Test

- `python3 -m unittest discover -s dev/tests` — mocked, no network, no rclone.
- Live without Google: `GDRIVE_ROOT`, `GDRIVE_HOME`, `GDRIVE_CACHE_DIR` to a temp dir; a profile whose `rclone.conf` holds `[gdrive] type = alias, remote = /some/dir` exercises mount/sync/umount/status/--persist (mount `/Folder`: `/` is a combine with `shared_with_me` + a Shared drives API call, Google only); `onboard` steps 1-9 render offline; `--mode auto` with `GDRIVE_SIGNIN_MIN=1` opens Chrome, waits, falls back (never sign in to a real account in tests); `index service` installs/removes a real LaunchAgent/timer (it logs "not logged in" per tick).
- Live Google: reads anywhere; writes only in a `gdrive-probe-*` folder of the tester's own Drive, removed afterwards. Pending live checks: `references/index.md`, progress notes.
- Per command: `-j` parses, `--fields` narrows both formats, `--no-header`, `| head -1` exits 0, every exit code it can produce.

## Friction rule

AI friction is a defect — confusing output, noisy errors, a missing capability: fix it in this repo, do not work around it.
