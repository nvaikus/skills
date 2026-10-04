# clockmaster web UI — developer notes

React 19 + TS + Vite + Tailwind v4. Source `frontend/`, build `dist/` (COMMITTED; server.py serves it per request, no restart needed). API contract: `../CLAUDE.md`.

## Workflow

| what | command (in `frontend/`) |
|---|---|
| mock UI, no backend | `npm run mock` → http://127.0.0.1:5180 (`dev/mock.js`, in-memory, dev only) |
| UI against a server | `CLOCKMASTER_API=http://127.0.0.1:7799 npx vite` (default proxy target 7788) |
| scratch backend | `python3 ../../../dev/demo_seed.py $D` then `CLOCKMASTER_HOME=$D CLOCKMASTER_SCHEDULER=null python3 ../server.py --port 7799` (from `skills/clockmaster-cli`: `src/web/server.py`) |
| check + build | `npm run build` (= `tsc --noEmit` + vite → `../dist`) — commit `dist/` with the source |

- Never aim dev at the real data dir or real scheduler: always `CLOCKMASTER_HOME=<scratch>` + `CLOCKMASTER_SCHEDULER=null`.
- Screenshots: `npx -y @playwright/cli@latest --browser=chromium …`; first time `install-browser chrome-for-testing`.
- Never click "Resume session" against a real server in tests: on macOS it opens a terminal.
- No `@types/node`: `vite.config.ts` is outside tsc (`declare const process`).

## Layers (imports only point down)

```
app/        composition: routing, theme, folds, modals, page title
features/   dashboard (TaskList = FilterBar/TaskColumn, TaskRow, RunStrip) timeline (useTimelineView, TimelineControls, TimelineLanes, TimelineLegend) task (TaskPage RunList RunPanel) editor (Edit/Delete dialogs)
ui/         dumb primitives; z-index only here via --z-* vars
data/       api.ts (fetch) store.ts (shared pollers) hooks.ts actions.ts (mutations + invalidate)
platform/web/  ALL browser APIs (storage, hash, theme, DOM listeners) — views never touch window/document
lib/        pure: types, format, status, route, groups, timeline math, edit diff, claude resume cmd
```

## Traps (each one bit the old UI)

- Polling: `useResource(key, …)` registry; one fetch per key across components. Keys must stay constant per screen — timeline snaps its fetch window (`lib/timeline.fetchWindow`), otherwise every tick = new key = request storm.
- On error the store keeps the last data → rename/poll races never blank the page.
- Rename: seed `task:<new>`/`runs:<new>` from the old cache, then `replace` the hash; do not invalidate old keys (404 noise).
- Editor snapshots the task once on open and POSTs only changed keys (`lib/edit.changedKeys`); polling must not rewrite the form.
- Schedule in the editor = the cron text field (`features/editor/ScheduleField`); under it the server's plain words + next run (`GET /api/schedule`, debounced; no cron parser in TS) and preset links that just fill the field. Users asked for cron as the main input: do not bring back a mode picker.
- Escape: one capture-phase listener (`ui/overlay`), only the top layer closes. Scrim click never closes a dialog. Every Esc handler spends the press: preventDefault on keydown AND keyup (`platform/web/dom`), else Safari/macOS also exits fullscreen; fallbacks check `defaultPrevented` and skip fields.
- ResizeObserver / wheel: callback refs (`platform/web/dom.observeWidth`, `onWheel` non-passive) — effect+ref misses late mounts.
- Timeline drag: pointer capture only after a 3 px move, else lane clicks die.
- Fold state: localStorage `clockmaster:folded`; arriving at a task inside a folded group unfolds it once (`revealed` ref), search ignores folds.
- Theme: class on `<html>` + tokens as `light-dark()` in `index.css`; `index.html` inline script applies the stored pref before first paint.
- Deep link from a notification: `GET /api/notify-click` polled; hash routes `#/<task>/<run-id>`.
- Resume: no dry endpoint for the command. `canOpenTerminal` false → button POSTs resume and shows the returned command; else "Open in terminal" + client-built command (`lib/claude`).
- One view (App): board = TaskColumn (left) + TimelineLanes (right) in one Card; row heights come from `ui/board.ROW` on BOTH sides — change them only there or names and lanes drift apart. Route `#/<task>` swaps the lanes for TaskPage (list stays, `lg`+); below `lg` the detail replaces the screen. Esc closes via `onEscapeIdle` (bubble phase, so overlays win).
- Layout is fluid full width (no max-w container; header shares the px). Nothing between the header and the board (no problem banner: a task row's red dot + red sticks say it; out of sync = the header's Sync pill): the list's filter + search live in TaskColumn's header (ROW.bar + ROW.head; phone: search icon opens the field), the time controls in the lanes' ROW.bar — both sides keep equal header heights. Board: task column on `surface`, lanes recessed on `bg-well` (+ inset shade), `border-line` divider; never shade the task column darker. Hover is App state shared by TaskRow and LaneRow. Planned runs = solid neutral pills (`PLANNED` = `--color-planned`, no outline, no status colour), width = lane `avgDurationSec` at this scale with the run 3px floor; thinned to every k-th (`lib/timeline.thinOut`) so neighbours keep ≥2px clear: never merged into a bar. Footer: hint under the task column (`COL_W` spacer; hidden below md), legend right-aligned under the lanes, Planned shown as the same pill. Run bars = real duration (running grows to now), 3px floor only. Wheel/vertical scroll zooms at the cursor; drag, horizontal scroll, Shift+wheel pan. No manual-run marker anywhere: how a run started is `lib/status.startedBy` (run header + 2nd tooltip line). TaskRow carries `RunStrip` (task's `lastRuns`, equal-height sticks, colour = status, click opens that run). Queue: tone `queue` (`--color-queue`, violet) = queued; skipped = `warn`. Timeline wait = `QUEUED` hatched band queuedAt→start (a queued run: up to now), opaque + `z-[1]` so it reads over overlapping run bars. Labels/tips/lengths of queued + never-started runs come from `lib/status` (`runTip`, `runLength`, `waitedSec`, `isLive`).
- TaskPage is runs-first: header, one inline meta row (`ui/Meta`: icon + muted label + value, no pills; settings items open EditDialog focused on that field, bell = notify popover), then RunList | RunPanel filling the height; below `@4xl` list or log, not both.
- TaskPage on lg+: the page is one screen tall (`lg:h-dvh` while a task is open) and the runs area flexes to the bottom — no fixed calc offsets. Run list is clamped to ~220–260px, the log takes the rest.
- Tooltips: never native `title`. Spread `{...tip(text)}` from `ui/Tooltip`; one `TooltipLayer` (main.tsx) shows it in ~100ms on mouse hover / :focus-visible. Touch or `(hover: none)`: no hover/focus tips, only a 500ms long press (its click is eaten), hidden on lift + 1.5s, scroll, any other tap. Hidden on hashchange, blur, tab hide, overlay push (`hideTips`), and when the anchor leaves the DOM (rAF isConnected). Only where it adds what is not on screen: run marks/sticks, planned pills, warning icons, icon-only buttons (= aria-label), cut text via `tipIfCut` (shown only while scrollWidth/Height > client), non-obvious settings (Meta `hint`). Never on names, labelled buttons, segments, switches, text badges, legend. Colours: `--color-tip*` tokens (dark = raised dark surface, never white).
- Empty search/filter: the board never changes shape. Lanes stay (`showLanes` = tasks exist), both sides keep `minBody` = unfiltered rows' height (`ui/board.ROW_PX`), the empty state sits in the task column, the title holds an invisible "N of N" so the search field never resizes. An open task stays open when the list filters it out.
- Phone input: every field is 16px below sm (`ui/Field` + a base-layer `!important` net), else iOS Safari zooms in on focus and stays zoomed. Never `maximum-scale`/`user-scalable=no`: body is `touch-action: manipulation` (page pinch works); the lanes are `touch-pan-y` and handle 2-pointer pinch (time zoom at the midpoint) and 1-finger horizontal pan themselves.
- Cursor: index.css base layer gives every clickable (button, roles button/switch/radio/tab/menuitem, a[href], label[for], summary, select) `cursor: pointer`, disabled `not-allowed`; a clickable div/li adds `cursor-pointer` itself.
- Timeline window lives in `useTimelineView` (App), not in the lanes: lanes unmount while a task is open.
- Only CSS file: `src/index.css` (tokens + base). Everything else is Tailwind classes.
