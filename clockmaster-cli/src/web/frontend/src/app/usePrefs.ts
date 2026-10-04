import { useCallback, useState } from "react";
import { load, save } from "../platform/web/storage";

/** Folded groups — per browser (localStorage), not in the task files. */
export function useFolds() {
  const [folded, setFolded] = useState<Set<string>>(() => new Set(load<string[]>("folded", [])));
  const write = (next: Set<string>) => {
    save("folded", [...next]);
    return next;
  };
  const toggle = useCallback((g: string) => setFolded((s) => {
    const n = new Set(s);
    if (!n.delete(g)) n.add(g);
    return write(n);
  }), []);
  const unfold = useCallback((g: string) => setFolded((s) => {
    if (!s.has(g)) return s;
    const n = new Set(s);
    n.delete(g);
    return write(n);
  }), []);
  return { folded, toggle, unfold };
}

export function useStored<T extends string>(key: string, fallback: T, allowed: readonly T[]) {
  const [v, setV] = useState<T>(() => {
    const x = load<string>(key, fallback);
    return (allowed as readonly string[]).includes(x) ? (x as T) : fallback;
  });
  const set = useCallback((x: T) => {
    save(key, x);
    setV(x);
  }, [key]);
  return [v, set] as const;
}
