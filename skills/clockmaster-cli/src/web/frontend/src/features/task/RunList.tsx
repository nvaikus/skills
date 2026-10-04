import type { Run } from "../../lib/types";
import { usd, when } from "../../lib/format";
import { runLabel, runLength, runTone } from "../../lib/status";
import { Card, SectionHead } from "../../ui/Card";
import { EmptyState, ErrorText, Loading } from "../../ui/Feedback";
import { Dot } from "../../ui/Status";
import { toneText } from "../../ui/tone";

export function RunList({ runs, loading, error, selected, now, onSelect }: { runs: Run[]; loading: boolean; error: string | null; selected: string | null; now: number; onSelect: (runId: string) => void }) {
  return (
    <section aria-labelledby="runs-h" className="flex min-h-0 min-w-0 flex-1 flex-col gap-2">
      <SectionHead id="runs-h" title={<>Run history{runs.length ? <span className="font-normal normal-case tracking-normal"> · {runs.length}</span> : null}</>} />
      <Card pad={false} fill>
        {error && !runs.length ? (
          <div className="p-3">
            <ErrorText>{error}</ErrorText>
          </div>
        ) : loading && !runs.length ? (
          <Loading />
        ) : !runs.length ? (
          <EmptyState icon="history" title="No runs yet">Press Run now to try it.</EmptyState>
        ) : (
          <ul className="max-h-[32rem] min-h-0 flex-1 divide-y divide-line-soft overflow-y-auto lg:max-h-none" aria-label="Runs">
            {runs.map((r) => {
              const on = r.runId === selected;
              const tone = runTone(r.status);
              const live = r.status === "running" || r.status === "queued";
              return (
                <li key={r.runId}>
                  <button
                    type="button"
                    aria-current={on || undefined}
                    onClick={() => onSelect(r.runId)}
                    className={`flex w-full items-center gap-2.5 px-3 py-2.5 text-left transition ${on ? "bg-accent/8" : "hover:bg-raised/60"}`}
                  >
                    <Dot tone={tone} pulse={live} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-body text-fg-1">{when(r.status === "queued" && r.queuedAt ? r.queuedAt : r.start, now)}</span>
                      <span className={`block truncate text-caption ${tone === "fail" || tone === "queue" ? toneText[tone] : "text-fg-3"}`}>
                        {runLabel(r.status)}
                        {r.exitCode != null && r.exitCode !== 0 ? ` · exit ${r.exitCode}` : ""}
                        {" · "}
                        {runLength(r, now)}
                      </span>
                    </span>
                    {r.costUsd != null && <span className="shrink-0 text-caption tabular-nums text-claude">{usd(r.costUsd)}</span>}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </Card>
    </section>
  );
}
