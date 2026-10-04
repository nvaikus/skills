// One shared poller per resource key. Any number of components can subscribe to
// the same key; the fetch runs once per tick at the shortest requested interval.
// Data survives key re-subscription (cache), so going back is instant and a
// refetch never blanks the screen.
import { useCallback, useEffect, useSyncExternalStore } from "react";
import { errorText } from "./api";

export interface Snapshot<T> {
  data: T | null;
  error: string | null;
  /** true until the first response for this key */
  pending: boolean;
  /** ms epoch of the last successful fetch */
  at: number;
}

interface Entry {
  fetcher: () => Promise<unknown>;
  snap: Snapshot<unknown>;
  subs: Map<symbol, { interval: number; cb: () => void }>;
  timer: ReturnType<typeof setTimeout> | null;
  inflight: boolean;
  again: boolean;
}

const entries = new Map<string, Entry>();
const EMPTY: Snapshot<never> = { data: null, error: null, pending: true, at: 0 };

function entry(key: string, fetcher: () => Promise<unknown>): Entry {
  let e = entries.get(key);
  if (!e) {
    e = { fetcher, snap: EMPTY, subs: new Map(), timer: null, inflight: false, again: false };
    entries.set(key, e);
  }
  e.fetcher = fetcher;
  return e;
}

function emit(e: Entry) {
  for (const s of e.subs.values()) s.cb();
}

function interval(e: Entry): number {
  let min = 0;
  for (const s of e.subs.values()) if (s.interval > 0 && (min === 0 || s.interval < min)) min = s.interval;
  return min;
}

function schedule(key: string, e: Entry) {
  if (e.timer) clearTimeout(e.timer);
  e.timer = null;
  const ms = interval(e);
  if (ms > 0 && e.subs.size) e.timer = setTimeout(() => void run(key), ms);
}

async function run(key: string) {
  const e = entries.get(key);
  if (!e) return;
  if (e.inflight) {
    e.again = true;
    return;
  }
  e.inflight = true;
  try {
    const data = await e.fetcher();
    e.snap = { data, error: null, pending: false, at: Date.now() };
  } catch (err) {
    e.snap = { ...e.snap, error: errorText(err), pending: false };
  }
  e.inflight = false;
  emit(e);
  if (e.again) {
    e.again = false;
    void run(key);
  } else schedule(key, e);
}

/** Refetch every resource whose key starts with one of the prefixes. */
export function invalidate(...prefixes: string[]) {
  for (const [key, e] of entries) if (e.subs.size && prefixes.some((p) => key.startsWith(p))) void run(key);
}

/** Seed / overwrite cached data (optimistic updates). */
export function patch<T>(key: string, fn: (d: T) => T) {
  const e = entries.get(key);
  if (e?.snap.data != null) {
    e.snap = { ...e.snap, data: fn(e.snap.data as T) };
    emit(e);
  }
}

/** key null = off. intervalMs 0 = fetch once per subscription. */
export function useResource<T>(key: string | null, fetcher: () => Promise<T>, intervalMs: number): Snapshot<T> & { refresh: () => void } {
  const subscribe = useCallback(
    (cb: () => void) => {
      if (!key) return () => {};
      const e = entry(key, fetcher);
      const id = Symbol(key);
      e.subs.set(id, { interval: intervalMs, cb });
      if (e.subs.size === 1 || e.snap === EMPTY || intervalMs === 0) void run(key);
      else schedule(key, e);
      return () => {
        e.subs.delete(id);
        schedule(key, e);
      };
    },
    // fetcher identity is irrelevant: the key names the resource
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [key, intervalMs],
  );
  const snap = useSyncExternalStore(subscribe, () => (key ? (entries.get(key)?.snap ?? EMPTY) : EMPTY)) as Snapshot<T>;
  // keep the newest fetcher closure (e.g. a changed query param under the same key)
  useEffect(() => {
    if (key) entry(key, fetcher);
  });
  const refresh = useCallback(() => key && void run(key), [key]);
  return { ...snap, refresh };
}

/** Last cached value of a key (no subscription) — e.g. to avoid a blink after rename. */
export function peek<T>(key: string): T | null {
  return (entries.get(key)?.snap.data as T) ?? null;
}

/** Create/overwrite a cache entry before anyone subscribes (rename: no "not found" blink). */
export function seed<T>(key: string, data: T) {
  const e = entries.get(key) ?? entry(key, () => Promise.resolve(data));
  e.snap = { data, error: null, pending: false, at: Date.now() };
  emit(e);
}
