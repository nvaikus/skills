// Timeline view math. A view is a [from, to) window in epoch ms. Pure.
import { clock, dayLabel } from "./format";

export interface View {
  from: number;
  to: number;
}

const MIN = 60e3;
const HOUR = 60 * MIN;
const DAY = 24 * HOUR;

export const MIN_SPAN = 15 * MIN;
export const MAX_SPAN = 92 * DAY; // server clamps the window to 92 days

export const PRESETS = [
  { id: "6h", label: "6h", span: 6 * HOUR },
  { id: "24h", label: "24h", span: DAY },
  { id: "3d", label: "3d", span: 3 * DAY },
  { id: "7d", label: "7d", span: 7 * DAY },
] as const;
export type PresetId = (typeof PRESETS)[number]["id"];

/**
 * Smallest preset span (min 24h, max 7d) in which every enabled task shows its
 * last run (in the 75% past) or its next run (in the 25% future).
 */
export function fitSpan(tasks: readonly { enabled: boolean; lastRun: { start: string } | null; nextRun: string | null }[], now: number): number {
  let need = DAY;
  for (const t of tasks) {
    if (!t.enabled) continue;
    const past = t.lastRun ? (now - Date.parse(t.lastRun.start)) / 0.75 : Infinity;
    const next = t.nextRun ? (Date.parse(t.nextRun) - now) / 0.25 : Infinity;
    const want = Math.min(past, next);
    if (isFinite(want)) need = Math.max(need, want);
  }
  return (PRESETS.find((p) => p.span >= need) ?? PRESETS[PRESETS.length - 1]).span;
}

/** A preset puts "now" at 75%: mostly history, a bit of what is coming. */
export function presetView(span: number, now: number): View {
  return { from: now - span * 0.75, to: now + span * 0.25 };
}

export function matchPreset(v: View, now: number): PresetId | null {
  for (const p of PRESETS) {
    const want = presetView(p.span, now);
    if (Math.abs(v.to - v.from - p.span) < 1000 && Math.abs(v.from - want.from) < 2 * MIN) return p.id;
  }
  return null;
}

/** Zoom by `factor` (<1 = in) keeping the time under `at` (0..1 of width) fixed. */
export function zoom(v: View, factor: number, at: number): View {
  const span = v.to - v.from;
  const next = Math.min(MAX_SPAN, Math.max(MIN_SPAN, span * factor));
  const pivot = v.from + span * at;
  return { from: pivot - next * at, to: pivot + next * (1 - at) };
}

export function pan(v: View, deltaMs: number): View {
  return { from: v.from + deltaMs, to: v.to + deltaMs };
}

export const xOf = (v: View, t: number) => (t - v.from) / (v.to - v.from);

const STEPS = [5 * MIN, 15 * MIN, 30 * MIN, HOUR, 2 * HOUR, 3 * HOUR, 6 * HOUR, 12 * HOUR, DAY, 2 * DAY, 7 * DAY, 14 * DAY];

export interface Tick {
  t: number;
  label: string;
  /** day boundary — drawn stronger and labeled with the date */
  major: boolean;
}

/** Ticks at least `minPx` apart, aligned to local time. */
export function ticks(v: View, widthPx: number, minPx = 84): Tick[] {
  const span = v.to - v.from;
  const step = STEPS.find((s) => (s / span) * widthPx >= minPx) ?? STEPS[STEPS.length - 1];
  const start = new Date(v.from);
  if (step >= DAY) start.setHours(0, 0, 0, 0);
  else {
    start.setMinutes(0, 0, 0);
    start.setHours(0);
  }
  const out: Tick[] = [];
  let t = start.getTime();
  // walk by local hours/days so DST days stay aligned to midnight
  for (let guard = 0; t < v.to && guard < 2000; guard++) {
    if (t >= v.from) {
      const d = new Date(t);
      const major = d.getHours() === 0 && d.getMinutes() === 0;
      out.push({ t, label: major || step >= DAY ? dayLabel(t) : clock(t), major });
    }
    const d = new Date(t);
    if (step >= DAY) d.setDate(d.getDate() + step / DAY);
    else d.setTime(d.getTime() + step);
    t = d.getTime();
  }
  return out;
}

/**
 * The window actually fetched: the view widened by one span on each side and
 * snapped to a coarse grid, so panning inside it keeps the same polling key.
 */
export function fetchWindow(v: View): View {
  const span = v.to - v.from;
  const grid = span <= DAY ? HOUR : span <= 7 * DAY ? 6 * HOUR : DAY;
  const from = Math.floor((v.from - span) / grid) * grid;
  const to = Math.ceil((v.to + span) / grid) * grid;
  return to - from > MAX_SPAN ? { from: v.from, to: v.from + MAX_SPAN } : { from, to };
}

/**
 * Show every k-th planned start so that shown pills sit at least `needPx` apart:
 * k = ceil(needPx / the tightest spacing between neighbours). Starts are sorted.
 */
export function thinOut(starts: readonly number[], needPx: number, pxPerMs: number): number {
  if (starts.length < 2 || !(pxPerMs > 0)) return 1;
  let tight = Infinity;
  for (let i = 1; i < starts.length; i++) tight = Math.min(tight, (starts[i] - starts[i - 1]) * pxPerMs);
  return tight >= needPx ? 1 : Math.ceil(needPx / Math.max(tight, 1e-6));
}
