import type { Task } from "./types";
import { isFailure } from "./status";

export type TaskFilter = "all" | "on" | "off";

export const FILTERS: readonly { value: TaskFilter; label: string; hint: string }[] = [
  { value: "all", label: "All", hint: "Every task" },
  { value: "on", label: "On", hint: "Tasks that run on their schedule" },
  { value: "off", label: "Off", hint: "Tasks turned off — they won't run on schedule" },
];

export interface Section {
  /** "" = tasks without a group */
  group: string;
  tasks: Task[];
  folded: boolean;
  failing: number;
  running: number;
  disabled: number;
}

/** A problem: the last run failed, or the system scheduler's copy differs (drift). */
export const hasProblem = (t: Task) =>
  t.drift || (t.lastRun != null && isFailure(t.lastRun.status));

export function matches(t: Task, q: string, f: TaskFilter): boolean {
  if (f === "on" && !t.enabled) return false;
  if (f === "off" && t.enabled) return false;
  if (!q) return true;
  const hay = `${t.name} ${t.group} ${t.description} ${t.scheduleText ?? ""} ${t.command}`.toLowerCase();
  return q.toLowerCase().split(/\s+/).every((w) => hay.includes(w));
}

/** Groups A→Z, then ungrouped; tasks A→Z inside. A filter never hides a match in a fold. */
export function sectionsOf(tasks: Task[], q: string, f: TaskFilter, folded: ReadonlySet<string>): Section[] {
  const byGroup = new Map<string, Task[]>();
  for (const t of tasks) {
    if (!matches(t, q, f)) continue;
    const list = byGroup.get(t.group) ?? [];
    list.push(t);
    byGroup.set(t.group, list);
  }
  const searching = q !== "" || f !== "all";
  return [...byGroup.entries()]
    .sort(([a], [b]) => (a === "" ? 1 : b === "" ? -1 : a.localeCompare(b)))
    .map(([group, list]) => ({
      group,
      tasks: list.sort((a, b) => a.name.localeCompare(b.name)),
      folded: group !== "" && !searching && folded.has(group),
      failing: list.filter(hasProblem).length,
      running: list.filter((t) => t.lastRun?.status === "running").length,
      disabled: list.filter((t) => !t.enabled).length,
    }));
}

export function filterCounts(tasks: Task[]): Record<TaskFilter, number> {
  return {
    all: tasks.length,
    on: tasks.filter((t) => t.enabled).length,
    off: tasks.filter((t) => !t.enabled).length,
  };
}

