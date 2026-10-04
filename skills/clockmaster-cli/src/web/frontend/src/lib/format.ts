// Human formatting: durations, relative times, money. Pure.

const pad = (n: number) => String(n).padStart(2, "0");

export function duration(sec: number | null | undefined): string {
  if (sec == null || !isFinite(sec)) return "—";
  if (sec < 1) return `${Math.round(sec * 1000)}ms`;
  if (sec < 60) return `${sec < 10 ? sec.toFixed(1) : Math.round(sec)}s`;
  const m = Math.floor(sec / 60);
  if (m < 60) return `${m}m ${pad(Math.round(sec % 60))}s`;
  const h = Math.floor(m / 60);
  if (h < 48) return `${h}h ${pad(m % 60)}m`;
  return `${Math.floor(h / 24)}d ${h % 24}h`;
}

/** "3m", "2h", "5d" — the compact span used by ago()/until(). */
export function span(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 45) return `${s}s`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return m % 60 && h < 3 ? `${h}h ${m % 60}m` : `${h}h`;
  const d = Math.round(h / 24);
  return `${d}d`;
}

export function ago(iso: string | null | undefined, now: number): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (!isFinite(t)) return "—";
  return now - t < 5000 ? "just now" : `${span(now - t)} ago`;
}

export function until(iso: string | null | undefined, now: number): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (!isFinite(t)) return "—";
  return t - now < 5000 ? "now" : `in ${span(t - now)}`;
}

function sameDay(a: Date, b: Date) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

const WD = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MO = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function clock(t: number | Date): string {
  const d = new Date(t);
  return `${d.getHours()}:${pad(d.getMinutes())}`;
}

/** "14:05", "Yesterday 14:05", "Tue 14:05", "3 Oct 14:05" relative to now. */
export function when(iso: string | null | undefined, now: number): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (!isFinite(d.getTime())) return "—";
  const n = new Date(now);
  if (sameDay(d, n)) return `Today ${clock(d)}`;
  const y = new Date(now - 864e5);
  if (sameDay(d, y)) return `Yesterday ${clock(d)}`;
  const t = new Date(now + 864e5);
  if (sameDay(d, t)) return `Tomorrow ${clock(d)}`;
  if (Math.abs(d.getTime() - now) < 6 * 864e5) return `${WD[d.getDay()]} ${clock(d)}`;
  return `${d.getDate()} ${MO[d.getMonth()]} ${clock(d)}`;
}

export function dayLabel(t: number): string {
  const d = new Date(t);
  return `${WD[d.getDay()]} ${d.getDate()} ${MO[d.getMonth()]}`;
}

export function fullStamp(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

export function usd(v: number | null | undefined): string {
  if (v == null) return "—";
  if (v === 0) return "$0";
  if (v < 0.01) return "<$0.01";
  return v < 100 ? `$${v.toFixed(2)}` : `$${Math.round(v)}`;
}

/** "2 h", "30 min", "1 h 30 min", "90 s" — for limits, not measurements. */
export function timeoutText(sec: number | null): string {
  if (sec == null || sec === 0) return "no limit";
  if (sec < 60) return `${sec} s`;
  const m = Math.round(sec / 60);
  const h = Math.floor(m / 60);
  if (!h) return `${m} min`;
  return m % 60 ? `${h} h ${m % 60} min` : `${h} h`;
}

export function keepText(keep: number | null): string {
  return keep == null ? "all runs" : `last ${keep} runs`;
}

/** "every day at 9:00" -> "Every day at 9:00" */
export const sentence = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : s);
