import { loadRaw, saveRaw } from "./storage";

export type ThemePref = "system" | "light" | "dark";

export function readThemePref(): ThemePref {
  const v = loadRaw("theme");
  return v === "light" || v === "dark" ? v : "system";
}

export function applyThemePref(p: ThemePref): void {
  const root = document.documentElement;
  root.classList.remove("light", "dark");
  if (p !== "system") root.classList.add(p);
  saveRaw("theme", p);
}

/** Effective scheme now, and a subscription to OS changes. */
export function systemDark(): boolean {
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}
export function onSystemThemeChange(cb: () => void): () => void {
  const mq = window.matchMedia("(prefers-color-scheme: dark)");
  mq.addEventListener("change", cb);
  return () => mq.removeEventListener("change", cb);
}
