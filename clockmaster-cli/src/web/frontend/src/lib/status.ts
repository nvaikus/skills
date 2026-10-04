import type { RunStatus, SchedState, Trigger } from "./types";
import { duration, when } from "./format";

export type Tone = "ok" | "fail" | "warn" | "live" | "queue" | "idle";

const RUN: Record<RunStatus, { label: string; tone: Tone }> = {
  queued: { label: "Queued", tone: "queue" },
  running: { label: "Running", tone: "live" },
  success: { label: "Succeeded", tone: "ok" },
  failed: { label: "Failed", tone: "fail" },
  timeout: { label: "Timed out", tone: "fail" },
  killed: { label: "Killed", tone: "fail" },
  stopped: { label: "Stopped", tone: "warn" },
  skipped: { label: "Skipped", tone: "warn" },
};

export const runTone = (s: RunStatus): Tone => RUN[s]?.tone ?? "idle";
export const runLabel = (s: RunStatus): string => RUN[s]?.label ?? s;
export const isFailure = (s: RunStatus) => s === "failed" || s === "timeout" || s === "killed";
/** Not finished yet: running, or waiting in the task's queue. */
export const isLive = (s: RunStatus) => s === "running" || s === "queued";

/** Seconds the run waited in the queue (0 = started at once). */
export function waitedSec(r: { start: string; queuedAt?: string }, status: RunStatus, now: number): number {
  if (!r.queuedAt) return 0;
  const end = status === "queued" ? now : Date.parse(r.start);
  return Math.max(0, (end - Date.parse(r.queuedAt)) / 1000);
}

/** Duration text of a run: grows while running, waiting time while queued. */
export function runLength(r: { start: string; durationSec: number | null; status: RunStatus; queuedAt?: string; reason?: string }, now: number): string {
  if (r.status === "queued") return "waiting " + duration(waitedSec(r, r.status, now));
  if (r.status === "skipped") return r.reason || "not run";
  if (r.status === "running") return "running " + duration((now - Date.parse(r.start)) / 1000);
  return duration(r.durationSec);
}

/** Tooltip text of a run mark/stick: outcome · when · length, how it started, the wait. */
export function runTip(r: { start: string; durationSec: number | null; status: RunStatus; trigger: Trigger; queuedAt?: string; reason?: string }, now: number): string {
  const w = waitedSec(r, r.status, now);
  const waited = r.status !== "queued" && w >= 1 ? `\nWaited ${duration(w)} in the queue` : "";
  return `${runLabel(r.status)} · ${when(r.queuedAt && r.status === "queued" ? r.queuedAt : r.start, now)} · ${runLength(r, now)}\n${startedBy(r.trigger)}${waited}`;
}

/** Plain-words explanation of the OS registration state (null = nothing to say). */
export function stateNote(state: SchedState, enabled: boolean): string | null {
  switch (state) {
    case "missing":
      return "Not registered with the system scheduler — sync to fix.";
    case "stale":
      return "The system scheduler has an outdated copy — sync to fix.";
    case "unloaded":
      return "Registered but not loaded — sync to fix.";
    case "off":
      return enabled ? "Enabled, but the scheduler has it off — sync to fix." : null;
    default:
      return null;
  }
}

export const NOTIFY_OPTIONS = [
  { value: "off", label: "Never", hint: "No notifications" },
  { value: "failure", label: "On failure", hint: "Only when a run fails" },
  { value: "on", label: "Always", hint: "After every run" },
] as const;

export function exitText(status: RunStatus, exitCode: number | null): string {
  if (status === "running" || status === "queued") return status;
  if (exitCode == null) return status === "success" ? "exit 0" : runLabel(status).toLowerCase();
  return `exit ${exitCode}`;
}

/** How a run was started, in plain words (run header, pill and stick tooltips). */
export const startedBy = (t: Trigger): string => (t === "manual" ? "Started manually" : "Started by schedule");
