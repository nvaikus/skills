import type { ReactNode } from "react";
import type { RunStatus } from "../lib/types";
import { runLabel, runTone, type Tone } from "../lib/status";
import { toneBg, toneSoft } from "./tone";
import { tip } from "./Tooltip";

export function Dot({ tone, pulse, size = 8 }: { tone: Tone; pulse?: boolean; size?: 6 | 8 | 10 }) {
  const s = size === 6 ? "size-1.5" : size === 10 ? "size-2.5" : "size-2";
  return <span aria-hidden="true" className={`inline-block shrink-0 rounded-full ${s} ${toneBg[tone]} ${pulse ? "animate-beat" : ""}`} />;
}

export function Badge({ tone, children }: { tone: Tone; children: ReactNode }) {
  return <span className={`inline-flex h-5 shrink-0 items-center gap-1 rounded-full px-2 text-micro font-semibold ${toneSoft[tone]}`}>{children}</span>;
}

export function RunBadge({ status }: { status: RunStatus }) {
  const tone = runTone(status);
  return (
    <Badge tone={tone}>
      <Dot tone={tone} size={6} pulse={status === "running"} />
      {runLabel(status)}
    </Badge>
  );
}

/** Recent outcomes, oldest → newest, as small bars (input is newest-first). */
export function StatusStrip({ statuses, slots = 10 }: { statuses: RunStatus[]; slots?: number }) {
  const list = statuses.slice(0, slots).reverse();
  const pad = slots - list.length;
  return (
    <span className="inline-flex items-end gap-[3px]" role="img" aria-label={list.length ? `Recent runs: ${list.map(runLabel).join(", ")}` : "No runs yet"}>
      {Array.from({ length: pad }, (_, i) => (
        <span key={"p" + i} className="h-1.5 w-1 rounded-full bg-line" />
      ))}
      {list.map((s, i) => (
        <span key={i} {...tip(runLabel(s))} className={`w-1 rounded-full ${toneBg[runTone(s)]} ${runTone(s) === "fail" ? "h-3.5" : "h-2.5"} ${s === "running" ? "animate-beat" : ""}`} />
      ))}
    </span>
  );
}
