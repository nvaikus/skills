# gmail — developer brief

Keep this file one screen. Entry `gmail.py` → `src/main.py:main`. Python 3.9+, stdlib only.

## Invariants — never break

- stdlib only, nothing installed on the system.
- A command never speaks HTTP and never prints: `api/` does the work, rows go to `ctx.write` / `ctx.text`. A test greps `src/commands` for `google.get|mutate` / `http.request`.
- Transport rail: `core/http.request` refuses non-GET without `allow_mutate=True`; only `api/google.mutate`, `api/auth` (token endpoint) and `api/unsubscribe._post` (RFC 8058 one-click POST to the sender's https URL; never a GET of a sender URL) pass it. `grep -rn allow_mutate src/commands` stays empty (a test enforces it).
- stdout = data; stderr = `# ` notes and `gmail: <error>`. Exit 0 · 1 · 2 · 5 onboard waits on the user · 6 in progress (API propagation) · 130. Raise `CliError`/`UsageError`/`Deadline`; never branch on message text (`e.status`, `google.reasons(e)`).
- Credentials never in argv: client from the profile config (imported from a file or another profile), the redirect URL from stdin.
- Every api function takes the profile explicitly (search runs profiles in parallel threads); `auth.access_token` is lock-protected.
- No permanent delete of mail: scopes `gmail.modify` + `gmail.settings.basic` (filters; older tokens lack it → `onboard --relogin`), no `messages.delete` / `batchDelete` routes.
- Config keys are contract (`core/config.DEFAULTS`).

## Layers

| file | owns |
|---|---|
| `main.py` · `registry.py` · `context.py` | argv, `--profile`, `<family> <verb>`, globals, exit codes · name → (module, help) · ctx |
| `core/` | http, output, config, profile (modes required/create/none/all/locate), paths, errors, stdin |
| `api/auth.py` · `google.py` | OAuth PKCE + token.json, granted scopes · REST, error → exit code, per-profile quota `Pacer` + 429/403-rate retry, `pmap`/`pmap_partial` |
| `api/mail.py` · `targets.py` | labels, search rows, lookup/locate, batchModify, trash · ids/-q → per-profile message ids, change receipt |
| `api/render.py` | payload → markdown: html_to_text, quote/signature strip, attachments numbered |
| `api/compose.py` · `drafting.py` | RFC 822 build, reply headers, drafts/send (upload > 4.5 MB) · shared draft flags, profile choice, draft lookup |
| `api/senders.py` · `unsubscribe.py` · `filters.py` | sender aggregation (threads.get for multi-hit threads) · List-Unsubscribe plan/execute · settings.filters + scope check |
| `api/onboarding.py` · `onboard_say.py` | answers, client reuse (gmail/gdrive profiles), `advance(env)`, `LiveEnv` · every user-facing text |
| `commands/<area>/<cmd>.py` | argparse + orchestration, < ~100 lines; `org/verbs.py` serves 8 verbs via `args.command` |

Shared logic moves down into `api/`, never sideways into another command.

## Add a command

1. `registry.COMMANDS["name"]` or `"family verb"` = `("src.commands.<area>.<file>", "one-line help")`.
2. Module: `FIELDS`, `EPILOG` (2–4 examples + traps), `add_args(p)`, `run(ctx, args)`; `WRITE = True` if it changes Gmail or local state; `PROFILE` = `required` (default) | `create` | `none` | `all` | `locate`. Never declare `-j/--fields/--no-header/--profile`.
3. Tests in `dev/tests/` (import `support` first: temp `GMAIL_ROOT`/`GDRIVE_ROOT`, profile `t`). `FakeGmail` (test_cli) routes by URL path, one mailbox per profile (the bearer token `tok-<profile>` names it); `FakeEnv` (test_onboard) replaces live onboarding checks.

## Route discovery

REST truth: developers.google.com/gmail/api/reference/rest (users.messages, threads, labels, drafts). Query syntax: support.google.com/mail/answer/7190.

## Test

- `python3 -m unittest discover -s dev/tests` — mocked, no network, < 1 s.
- Live: reads anywhere; writes only on messages/labels/drafts the test created (label `gmail-probe-*`, drafts to the account's own address), removed afterwards.
- Per command: `-j` parses, `--fields` narrows, `--no-header`, `| head -1` exits 0, every exit code it can produce.

## Friction rule

AI friction is a defect — confusing output, noisy errors, a missing capability: fix it in this repo, do not work around it.
