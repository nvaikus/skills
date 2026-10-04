// Mutations: call the API, then refetch what they changed.
import type { EditForm, Notify, Task } from "../lib/types";
import { api } from "./api";
import { invalidate, patch } from "./store";

const touched = (name: string) => ["tasks", `task:${name}`, `runs:${name}`, "drift", "timeline"];

export async function setEnabled(name: string, enabled: boolean) {
  patch<Task[]>("tasks", (ts) => ts.map((t) => (t.name === name ? { ...t, enabled } : t)));
  patch<Task>(`task:${name}`, (t) => ({ ...t, enabled }));
  try {
    return await api.setEnabled(name, enabled);
  } finally {
    invalidate(...touched(name));
  }
}

export async function setNotify(name: string, notify: Notify) {
  patch<Task>(`task:${name}`, (t) => ({ ...t, notify }));
  try {
    return await api.setNotify(name, notify);
  } finally {
    invalidate("tasks", `task:${name}`);
  }
}

export async function setSound(name: string, sound: string) {
  patch<Task>(`task:${name}`, (t) => ({ ...t, sound }));
  try {
    return await api.setSound(name, sound);
  } finally {
    invalidate("tasks", `task:${name}`);
  }
}

export async function runNow(name: string) {
  const res = await api.runNow(name);
  // the run shows up on disk ~0.5 s later; poll a few times quickly
  for (const ms of [600, 1500, 3000]) setTimeout(() => invalidate(...touched(name)), ms);
  return res;
}

export async function stopRun(name: string, runId: string) {
  try {
    return await api.stop(name, runId);
  } finally {
    invalidate(...touched(name), `log:${name}/${runId}`);
  }
}

export const resumeRun = (name: string, runId: string) => api.resume(name, runId);

export async function editTask(name: string, changes: Partial<EditForm>) {
  const res = await api.edit(name, changes);
  // renamed: the old keys would only 404 while the page switches over
  invalidate(...touched(res.name));
  return res;
}

export async function deleteTask(name: string, purgeRuns: boolean) {
  const res = await api.remove(name, purgeRuns);
  invalidate("tasks", "drift", "timeline");
  return res;
}

export async function syncAll() {
  const res = await api.sync();
  invalidate("tasks", "task:", "drift");
  return res;
}
