// Hash routing: #/ = dashboard, #/<task> = task, #/<task>/<run-id> = a run.

export type Route =
  | { kind: "home" }
  | { kind: "task"; task: string; runId: string | null };

export function parseRoute(hash: string): Route {
  const parts = hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(safeDecode);
  if (!parts.length) return { kind: "home" };
  return { kind: "task", task: parts[0], runId: parts[1] ?? null };
}

export function routeHash(r: Route): string {
  if (r.kind === "home") return "#/";
  return `#/${encodeURIComponent(r.task)}${r.runId ? "/" + encodeURIComponent(r.runId) : ""}`;
}

function safeDecode(s: string) {
  try {
    return decodeURIComponent(s);
  } catch {
    return s;
  }
}
