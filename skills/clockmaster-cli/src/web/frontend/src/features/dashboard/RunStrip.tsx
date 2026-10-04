import type { StripRun } from "../../lib/types";
import { runTip, runTone } from "../../lib/status";
import { toneBg } from "../../ui/tone";
import { tip } from "../../ui/Tooltip";

// bars kept per width: phone 8, sm 12, lg all 20 (the oldest drop first)
const HIDE = (age: number) => (age >= 12 ? "hidden lg:flex" : age >= 8 ? "hidden sm:flex" : "flex");

/**
 * The task's last runs as sticks, oldest left, newest right. All the same height:
 * colour = outcome, the rest (time, duration) is in the tooltip. A click opens that run.
 */
export function RunStrip({ runs, now, onOpen }: { runs: StripRun[]; now: number; onOpen: (runId: string) => void }) {
  if (!runs.length) return null;
  return (
    <span className="flex h-4 shrink-0 items-center" aria-label={`Last ${runs.length} runs`}>
      {runs
        .map((r, age) => {
          const label = runTip(r, now);
          return (
            <button
              key={r.runId}
              type="button"
              {...tip(label)}
              aria-label={label}
              onClick={(e) => {
                e.stopPropagation();
                onOpen(r.runId);
              }}
              className={`group h-full w-[5px] items-center justify-center ${HIDE(age)}`}
            >
              <span className={`h-3 w-[3px] rounded-full transition group-hover:brightness-125 ${toneBg[runTone(r.status)]} ${r.status === "running" ? "animate-beat" : ""}`} />
            </button>
          );
        })
        .reverse()}
    </span>
  );
}
