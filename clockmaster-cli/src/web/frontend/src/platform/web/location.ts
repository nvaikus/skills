export const readHash = () => window.location.hash;

export function onHashChange(cb: () => void): () => void {
  window.addEventListener("hashchange", cb);
  return () => window.removeEventListener("hashchange", cb);
}

/** push = new history entry (Back returns); replace = correct the current one. */
export function setHash(hash: string, mode: "push" | "replace" = "push"): void {
  if (window.location.hash === hash) return;
  if (mode === "replace") {
    history.replaceState(null, "", hash);
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  } else window.location.hash = hash;
}
