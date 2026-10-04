// Typed fetch over the clockmaster HTTP API. Views never call fetch.
import type { AppInfo, EditForm, Lane, Notify, ResumeResult, Run, RunHit, SchedulePreview, Task, TaskDetail } from "../lib/types";

let BASE = "";
export const setApiBase = (b: string) => void (BASE = b.replace(/\/$/, ""));

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function req<T>(method: string, path: string, body?: unknown, as: "json" | "text" = "json"): Promise<T> {
  let res: Response;
  try {
    res = await fetch(BASE + path, {
      method,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, "Can't reach the clockmaster server. Is `clockmaster ui` running?");
  }
  if (!res.ok) {
    const text = await res.text();
    let msg = text;
    try {
      msg = (JSON.parse(text) as { error?: string }).error ?? text;
    } catch {
      /* plain text error */
    }
    throw new ApiError(res.status, msg.trim() || `${res.status} ${res.statusText}`);
  }
  return (as === "text" ? res.text() : res.json()) as Promise<T>;
}

const t = (name: string) => `/api/tasks/${encodeURIComponent(name)}`;
const r = (name: string, runId: string) => `${t(name)}/runs/${encodeURIComponent(runId)}`;

export const api = {
  app: () => req<AppInfo>("GET", "/api/app"),
  drift: () => req<{ drift: number }>("GET", "/api/drift"),
  tasks: () => req<Task[]>("GET", "/api/tasks"),
  task: (name: string) => req<TaskDetail>("GET", t(name)),
  runs: (name: string, n = 50) => req<Run[]>("GET", `${t(name)}/runs?n=${n}`),
  log: (name: string, runId: string) => req<string>("GET", `${r(name, runId)}/log`, undefined, "text"),
  timeline: (from: number, to: number) =>
    req<Lane[]>("GET", `/api/timeline?from=${encodeURIComponent(new Date(from).toISOString())}&to=${encodeURIComponent(new Date(to).toISOString())}`),
  searchRuns: (q: string, limit: number) => req<RunHit[]>("GET", `/api/runs/search?q=${encodeURIComponent(q)}&limit=${limit}`),
  schedule: (cron: string) => req<SchedulePreview>("GET", `/api/schedule?cron=${encodeURIComponent(cron)}`),
  notifyClick: () => req<{ task?: string; runId?: string }>("GET", "/api/notify-click"),

  edit: (name: string, changes: Partial<EditForm>) => req<{ ok: boolean; name: string; syncOutput?: string }>("POST", t(name), changes),
  remove: (name: string, purgeRuns: boolean) =>
    req<{ ok: boolean; deleted: string; purgedRuns: boolean; syncOutput?: string }>("DELETE", t(name) + (purgeRuns ? "?purge-runs=1" : "")),
  runNow: (name: string) => req<{ started: boolean }>("POST", `${t(name)}/run`, {}),
  setEnabled: (name: string, enabled: boolean) => req<{ ok: boolean; enabled: boolean }>("POST", `${t(name)}/enabled`, { enabled }),
  setNotify: (name: string, notify: Notify) => req<{ ok: boolean; notify: Notify }>("POST", `${t(name)}/notify`, { notify }),
  setSound: (name: string, sound: string) => req<{ ok: boolean; sound: string }>("POST", `${t(name)}/sound`, { sound }),
  stop: (name: string, runId: string) => req<{ run: Run; note?: string }>("POST", `${r(name, runId)}/stop`, {}),
  resume: (name: string, runId: string) => req<ResumeResult>("POST", `${r(name, runId)}/resume`, {}),
  sync: () => req<{ ok: boolean; output: string }>("POST", "/api/sync", {}),
};

export function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}
