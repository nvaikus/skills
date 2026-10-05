# icloud-calendar — developer brief

Keep this file one screen. Entry `icloud-calendar.py` → `src/main.py:main`. Python 3.9+, stdlib only.

## Invariants — never break

- stdlib only (no caldav/icalendar/dateutil); zoneinfo for zones.
- A command never speaks HTTP and never prints: `api/` does the work, rows go to `ctx.write` / `ctx.text`. A test greps `src/commands` for `allow_mutate|http.request|.mutate(`.
- Transport rail: `core/http.request` refuses non-read methods without `allow_mutate=True`; only `api/dav.Session.mutate` passes it. Basic auth is sent only to `https://*.icloud.com` (`http.trusted`); redirects are followed by hand (method + body kept).
- The password never reaches argv, files, output or exceptions: env var named in config or `password_cmd`.
- Write gate: `calendars.write_gate` before every event PUT/DELETE (ro shares, subscribed, reminders → UsageError exit 2). Calendar MKCALENDAR/DELETE: `calendars.create/remove` (dup name → exit 2; delete own only, exact name/id, non-empty needs --force).
- Writes are conditional: new = `If-None-Match: *`, edit/delete = `If-Match: <etag>`.
- ICS edits change only the touched properties (`ics.Component.set`); unknown properties and sub-components survive.
- stdout = data; stderr = `# ` notes and `icloud-calendar: <error>`. Exit 0 · 1 · 2 · 5 · 130. Branch on `e.status` / `AuthError`, never on message text.
- Config keys are contract (`core/config.DEFAULTS`).

## Layers

| file | owns |
|---|---|
| `main.py` · `registry.py` · `context.py` | argv, globals (`--profile --tz`), exit codes · name → (module, help) · ctx (lazy session + calendar list) |
| `core/` | http (rail, redirects, retries), output, config, profile, paths, errors, stdin |
| `api/dav.py` | credentials, Session (PROPFIND/REPORT/GET/mutate, 401 → AuthError), multistatus parsing |
| `api/calendars.py` | discovery + cache, kind/access/owner classification, `pick`, `write_gate`, default choice |
| `api/events.py` · `edits.py` | range query (server expand + local fallback), feeds, uid lookup, build/put/delete · time-flag resolution |
| `api/geo.py` | location → map pin: Nominatim/Photon lookup (no auth, retries=0), X-APPLE-STRUCTURED-LOCATION + GEO |
| `api/ics.py` · `recur.py` · `tz.py` · `when.py` | iCalendar parse/serialize + VTIMEZONE · RRULE expansion · zone resolution · user time input |
| `api/onboarding.py` · `invites.py` | onboarding steps + texts · notification collection parsing |
| `commands/<area>/<cmd>.py` | argparse + orchestration, < ~100 lines; shared event flags in `event/_common.py` |

## Add a command

1. `registry.COMMANDS["name"] = ("src.commands.<area>.<file>", "one-line help")`.
2. Module: `FIELDS`, `EPILOG`, `add_args(p)`, `run(ctx, args)`; `PROFILE` = `required` (default) | `create` | `none`. Never declare `-j/--fields/--no-header/--profile/--tz`.
3. Tests in `dev/tests/` (import `support` first: temp `ICAL_ROOT`, fake creds, TZ=Europe/Lisbon, profile `t`). `FakeDav` patches `http._send`; fixtures `home.xml` hold one calendar of every kind.

## Test

- `python3 -m unittest discover -s dev/tests` — mocked, no network, < 1 s.
- Live (creds in env): `calendars`; `add --title probe-$RANDOM --start 'tomorrow 23:00' --cal <own>` → `list --grep probe` → `delete UID`; never write to shared calendars in tests.

## Friction rule

AI friction is a defect — confusing output, noisy errors, a missing capability: fix it in this repo, do not work around it.
