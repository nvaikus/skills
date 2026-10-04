import type { EditForm, Task } from "./types";

export const NAME_RE = /^[a-z0-9][a-z0-9-]*$/;

export function timeoutField(sec: number | null): string {
  if (sec == null || sec === 0) return "none";
  if (sec % 3600 === 0) return `${sec / 3600}h`;
  if (sec % 60 === 0) return `${sec / 60}m`;
  return `${sec}s`;
}

/** Snapshot taken ONCE when the editor opens — polling must not reset the form. */
export function formOf(t: Task): EditForm {
  return {
    name: t.name,
    schedule: t.schedule,
    command: t.command,
    workdir: t.workdir,
    timeout: timeoutField(t.timeoutSec),
    keep: t.keep == null ? "unlimited" : String(t.keep),
    description: t.description,
    group: t.group,
    parallel: String(t.parallel ?? 1),
    queue: String(t.queue ?? 20),
  };
}

/** Only keys the user changed go to the server (untouched defaults stay implicit). */
export function changedKeys(orig: EditForm, cur: EditForm): Partial<EditForm> {
  const out: Partial<EditForm> = {};
  for (const k of Object.keys(cur) as (keyof EditForm)[]) {
    if (cur[k].trim() !== orig[k].trim()) out[k] = cur[k].trim();
  }
  return out;
}

/** Client-side checks that save a round-trip; the server stays the authority. */
export function formProblems(f: EditForm): Partial<Record<keyof EditForm, string>> {
  const p: Partial<Record<keyof EditForm, string>> = {};
  if (!NAME_RE.test(f.name.trim())) p.name = "Lowercase letters, digits and dashes; starts with a letter or digit.";
  if (f.schedule.trim().split(/\s+/).length !== 5) p.schedule = "Five fields: minute hour day month weekday.";
  if (!f.command.trim()) p.command = "Required.";
  if (f.group.trim() && !NAME_RE.test(f.group.trim())) p.group = "Lowercase letters, digits and dashes.";
  if (/[\r\n]/.test(f.command)) p.command = "One line only.";
  if (f.parallel.trim() && !/^[1-9]\d*$/.test(f.parallel.trim())) p.parallel = "A whole number, 1 or more.";
  if (f.queue.trim() && !/^\d+$/.test(f.queue.trim())) p.queue = "A whole number, 0 or more.";
  return p;
}
