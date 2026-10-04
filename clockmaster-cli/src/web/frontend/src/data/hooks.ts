import { useEffect, useState } from "react";
import type { RunHit, SchedulePreview } from "../lib/types";
import { api, errorText } from "./api";
import { useResource } from "./store";

const POLL = 3000;

export const useApp = () => useResource("app", api.app, 60000);
export const useTasks = () => useResource("tasks", api.tasks, POLL);
export const useDrift = () => useResource("drift", () => api.drift(), 5000);
export const useTask = (name: string | null) => useResource(name ? `task:${name}` : null, () => api.task(name!), POLL);
export const useRuns = (name: string | null, live: boolean) =>
  useResource(name ? `runs:${name}` : null, () => api.runs(name!, 50), live ? 1500 : POLL);
/** Log of one run: live-tails while the run is running, fetched once otherwise. */
export const useLog = (name: string | null, runId: string | null, live: boolean) =>
  useResource(name && runId ? `log:${name}/${runId}` : null, () => api.log(name!, runId!), live ? 1500 : 0);
/** `from`/`to` must be snapped (lib/timeline fetchWindow) so the key stays constant while panning. */
export const useTimeline = (from: number, to: number, enabled = true) =>
  useResource(enabled ? `timeline:${from}-${to}` : null, () => api.timeline(from, to), 10000);

/** Re-render on an interval so relative times stay honest. */
export function useNow(ms = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(id);
  }, [ms]);
  return now;
}

/** A notification click lands in /api/notify-click (consumed once); hand it to `go`. */
export function useNotifyClick(go: (task: string, runId: string | null) => void) {
  useEffect(() => {
    let live = true;
    const tick = async () => {
      try {
        const c = await api.notifyClick();
        if (live && c.task) go(c.task, c.runId ?? null);
      } catch {
        /* server down: the main pollers already show it */
      }
    };
    void tick();
    const id = setInterval(tick, 2000);
    return () => {
      live = false;
      clearInterval(id);
    };
  }, [go]);
}

/** Words + next runs for a cron, from the server's parser. Debounced; stale answers dropped. */
export function useSchedulePreview(cron: string | null, delay = 250): { data: SchedulePreview | null; error: string | null; stale: boolean } {
  const [out, setOut] = useState<{ key: string | null; data: SchedulePreview | null; error: string | null }>({ key: null, data: null, error: null });
  useEffect(() => {
    if (!cron) return;
    let live = true;
    const id = setTimeout(async () => {
      try {
        const data = await api.schedule(cron);
        if (live) setOut({ key: cron, data, error: null });
      } catch (e) {
        if (live) setOut({ key: cron, data: null, error: errorText(e) });
      }
    }, delay);
    return () => {
      live = false;
      clearTimeout(id);
    };
  }, [cron, delay]);
  // the last answer stays on screen while the next one loads (no flicker per keystroke)
  return { data: out.data, error: out.error, stale: out.key !== cron };
}

/** Run ids are searched from this many typed characters on (shorter = every run matches). */
export const RUN_SEARCH_MIN = 4;
export const RUN_SEARCH_LIMIT = 20;

/**
 * Runs whose id contains the search text. The server is asked only after typing pauses
 * (one key per settled query, so polling never storms); meanwhile the last answer is
 * narrowed client-side, so hits never show a run the current text does not match.
 * `settled` = the answer for exactly this text is in (gates "Nothing matches").
 */
export function useRunSearch(query: string, delay = 300): { hits: RunHit[]; capped: boolean; settled: boolean } {
  const q = query.trim().toLowerCase();
  const active = q.length >= RUN_SEARCH_MIN;
  const [asked, setAsked] = useState("");
  useEffect(() => {
    if (!active) return;
    const id = setTimeout(() => setAsked(q), delay);
    return () => clearTimeout(id);
  }, [q, active, delay]);
  const res = useResource(active && asked ? `runsearch:${asked}` : null, () => api.searchRuns(asked, RUN_SEARCH_LIMIT), 5000);
  // keep the previous answer on screen while the next key loads
  const [last, setLast] = useState<{ q: string; data: RunHit[] } | null>(null);
  if (res.data && asked && (last?.q !== asked || last.data !== res.data)) setLast({ q: asked, data: res.data });
  if (!active) return { hits: [], capped: false, settled: true };
  const data = res.data ?? (last && q.includes(last.q) ? last.data : []);
  const hits = data.filter((h) => h.runId.toLowerCase().includes(q));
  return { hits, capped: data.length >= RUN_SEARCH_LIMIT, settled: asked === q && !res.pending };
}
