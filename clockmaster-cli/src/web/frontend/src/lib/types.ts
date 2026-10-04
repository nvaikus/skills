// Shapes of the clockmaster HTTP API (contract: clockmaster-cli/src/CLAUDE.md).
// Optional fields are optional on disk too (old metas lack them) — never assume.

export type RunStatus = "queued" | "running" | "success" | "failed" | "timeout" | "killed" | "stopped" | "skipped";
export type Notify = "off" | "on" | "failure";
export type SchedState = "ok" | "off" | "missing" | "stale" | "unloaded";
export type Trigger = "manual" | "schedule";

export interface AppInfo {
  app: string;
  platform: "linux" | "darwin" | "win32" | string;
  backend: string;
  dataDir: string;
  notes: string[];
  sounds: string[];
  canOpenTerminal: boolean;
  /** plain names of the channels a finished run reaches now ("Desktop", "Telegram", …) */
  notifyChannels?: string[];
}

export interface Run {
  task: string;
  runId: string;
  trigger: Trigger;
  command?: string;
  workdir?: string;
  sessionId?: string;
  start: string;
  end?: string | null;
  status: RunStatus;
  exitCode: number | null;
  durationSec: number | null;
  hasSession?: boolean;
  costUsd?: number | null;
  /** when the run arrived and had to wait for a free slot (start = actual start) */
  queuedAt?: string;
  /** why a run was skipped ("queue full (20 waiting)") */
  reason?: string;
}

export interface Task {
  name: string;
  group: string;
  description: string;
  enabled: boolean;
  notify: Notify;
  sound: string;
  schedule: string;
  scheduleText?: string;
  command: string;
  workdir: string;
  timeoutSec: number | null;
  keep: number | null;
  /** runs at the same time (default 1); more wait in a queue of `queue` */
  parallel: number;
  queue: number;
  /** runs waiting in the queue right now */
  queued: number;
  state: SchedState;
  drift: boolean;
  nextRun: string | null;
  lastRun: Run | null;
  /** newest first, max 20: the task row's run strip */
  lastRuns: StripRun[];
  /** mean duration of the last 20 succeeded/failed runs; null without any */
  avgDurationSec: number | null;
}

export interface TaskDetail extends Task {
  yaml: string;
  spentUsd: number | null;
}

export interface SchedulePreview {
  cron: string;
  text: string;
  next: string[];
}

export interface LaneRun {
  runId: string;
  start: string;
  end: string | null;
  durationSec: number | null;
  status: RunStatus;
  trigger: Trigger;
  exitCode: number | null;
  queuedAt?: string;
  reason?: string;
}

export interface Lane {
  task: string;
  group: string;
  enabled: boolean;
  runs: LaneRun[];
  planned: string[];
  plannedTruncated: boolean;
  /** the server sent every n-th start (dense schedule over a long window); 1 = all */
  plannedEvery: number;
  /** mean duration of the task's last 20 succeeded/failed runs: a planned pill's width */
  avgDurationSec: number | null;
}

/** Editable keys of POST /api/tasks/:name (all strings; blank optional = default). */
export interface EditForm {
  name: string;
  schedule: string;
  command: string;
  workdir: string;
  timeout: string;
  keep: string;
  description: string;
  group: string;
  parallel: string;
  queue: string;
}

export interface ResumeResult {
  opened: boolean;
  command: string;
  note?: string;
}

export interface StripRun {
  runId: string;
  status: RunStatus;
  start: string;
  durationSec: number | null;
  trigger: Trigger;
  queuedAt?: string;
  reason?: string;
}

/** GET /api/runs/search: a run whose id matched the search box. */
export interface RunHit {
  task: string;
  runId: string;
  status: RunStatus;
  start: string | null;
  durationSec: number | null;
}
