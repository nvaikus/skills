import { useEffect, useRef, useState } from "react";
import type { RunHit, Task } from "../../lib/types";
import { FILTERS, type Section, type TaskFilter } from "../../lib/groups";
import { when } from "../../lib/format";
import { runLabel, runTone } from "../../lib/status";
import { EmptyState, ErrorText, Loading } from "../../ui/Feedback";
import { Segmented } from "../../ui/Segmented";
import { Icon } from "../../ui/Icon";
import { IconButton } from "../../ui/Button";
import { SearchField } from "../../ui/Field";
import { Badge, Dot } from "../../ui/Status";
import { tipIfCut } from "../../ui/Tooltip";
import { ROW } from "../../ui/board";
import { TaskRow } from "./TaskRow";

/** All / On / Off with counts; a zero count stays visible (muted) so the meaning shows. */
export function FilterBar({ filter, onFilter, counts }: { filter: TaskFilter; onFilter: (f: TaskFilter) => void; counts: Record<TaskFilter, number> }) {
  return (
    <Segmented
      size="sm"
      label="Show tasks"
      options={FILTERS.map((f) => ({
        value: f.value,
        label: (
          <>
            {f.label}
            <span className={`tabular-nums ${counts[f.value] ? "text-fg-2" : "text-fg-3/70"}`}>{counts[f.value]}</span>
          </>
        ),
      }))}
      value={filter}
      onChange={onFilter}
    />
  );
}

export interface TaskColumnProps {
  sections: Section[];
  total: number;
  shown: number;
  loading: boolean;
  error: string | null;
  onFold: (group: string) => void;
  onOpen: (task: string) => void;
  onOpenRun: (task: string, runId: string) => void;
  now: number;
  onEnabled: (task: Task, on: boolean) => void;
  current: string | null;
  /** row under the pointer, shared with the lanes so the highlight spans both sides */
  hover: string | null;
  onHover: (task: string | null) => void;
  filter: TaskFilter;
  onFilter: (f: TaskFilter) => void;
  counts: Record<TaskFilter, number>;
  query: string;
  onQuery: (q: string) => void;
  /** px kept for the rows (same as the lanes), so a search/filter never moves the board */
  minBody: number;
  /** empty search/filter result: back to every task */
  onClear: () => void;
  /** runs whose id matches the search text (data/hooks useRunSearch) */
  runs: { hits: RunHit[]; capped: boolean; settled: boolean };
}

/** Left column of the board: one fixed-height row per task, group rows in between. */
export function TaskColumn(p: TaskColumnProps) {
  const grouped = p.sections.some((s) => s.group !== "");
  return (
    <div className="min-w-0">
      <ColumnHead {...p} />
      {p.error && !p.sections.length ? (
        <div className="p-4">
          <ErrorText>{p.error}</ErrorText>
        </div>
      ) : p.loading ? (
        <Loading />
      ) : !p.total ? (
        <EmptyState title="No tasks yet">
          Ask Claude to schedule something, or run <code className="font-mono">clockmaster add</code>.
        </EmptyState>
      ) : (
        // rows come and go with search/filter; the body keeps its height so nothing else moves
        <div style={{ minHeight: p.minBody }}>
          {!p.sections.length ? (
            // "Nothing matches" only when no run matches either (and the run search has answered)
            !p.runs.hits.length && p.runs.settled && (
              <EmptyState compact icon="search" title="Nothing matches">
                <button type="button" onClick={p.onClear} className="font-medium text-accent hover:underline">
                  {p.query ? "Clear search" : "Show all tasks"}
                </button>
              </EmptyState>
            )
          ) : (
            <ul aria-label="Tasks">
              {p.sections.map((s) => (
                <li key={s.group || "_none"}>
                  {grouped && <GroupHeader section={s} onFold={() => p.onFold(s.group)} />}
                  {!s.folded && (
                    <ul>
                      {s.tasks.map((t) => (
                        <TaskRow
                          key={t.name}
                          task={t}
                          current={p.current === t.name}
                          hovered={p.hover === t.name}
                          onHover={(on) => p.onHover(on ? t.name : null)}
                          onOpen={() => p.onOpen(t.name)}
                          onOpenRun={(id) => p.onOpenRun(t.name, id)}
                          now={p.now}
                          onEnabled={(on) => p.onEnabled(t, on)}
                        />
                      ))}
                    </ul>
                  )}
                </li>
              ))}
            </ul>
          )}
          {p.runs.hits.length > 0 && <RunHits hits={p.runs.hits} capped={p.runs.capped} query={p.query} now={p.now} onOpenRun={p.onOpenRun} />}
        </div>
      )}
    </div>
  );
}

/** Search hits by run id, under the matching tasks (below the rows, so the lanes stay aligned). */
function RunHits({ hits, capped, query, now, onOpenRun }: { hits: RunHit[]; capped: boolean; query: string; now: number; onOpenRun: (task: string, runId: string) => void }) {
  return (
    <section aria-label="Runs">
      <div className="flex h-8 items-center gap-2 border-b border-line-soft bg-sunken px-3 text-caption font-semibold text-fg-2">
        <span className="uppercase tracking-wider text-fg-3">Runs</span>
        <span className="font-normal text-fg-3 tabular-nums">{hits.length}{capped ? "+" : ""}</span>
      </div>
      <ul>
        {hits.map((h) => (
          <li key={`${h.task}/${h.runId}`} className="border-b border-line-soft">
            <button
              type="button"
              onClick={() => onOpenRun(h.task, h.runId)}
              aria-label={`Open run ${h.runId} of ${h.task} (${runLabel(h.status)})`}
              className="flex w-full items-center gap-2.5 px-3 py-2 text-left transition-colors hover:bg-accent/5"
            >
              <Dot tone={runTone(h.status)} pulse={h.status === "running"} />
              <span className="min-w-0 flex-1">
                <span className="block truncate font-mono text-micro text-fg-1 sm:text-caption" {...tipIfCut(h.runId)}>
                  <Marked text={h.runId} part={query.trim()} />
                </span>
                <span className="block truncate text-caption text-fg-2" {...tipIfCut(`${h.task} · ${when(h.start, now)}`)}>
                  {h.task}
                  {/* phone: the narrow column keeps the task name; the run id already carries date + time */}
                  <span className="hidden sm:inline"> · {when(h.start, now)}</span>
                </span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** `text` with the first case-insensitive occurrence of `part` highlighted. */
function Marked({ text, part }: { text: string; part: string }) {
  const at = part ? text.toLowerCase().indexOf(part.toLowerCase()) : -1;
  if (at < 0) return <>{text}</>;
  return (
    <>
      {text.slice(0, at)}
      <mark className="rounded-sm bg-accent/20 text-fg-1">{text.slice(at, at + part.length)}</mark>
      {text.slice(at + part.length)}
    </>
  );
}

function GroupHeader({ section: s, onFold }: { section: Section; onFold: () => void }) {
  const canFold = s.group !== "";
  return (
    <button
      type="button"
      onClick={canFold ? onFold : undefined}
      aria-expanded={canFold ? !s.folded : undefined}
      disabled={!canFold}
      className={`flex w-full items-center gap-2 bg-sunken px-3 text-left text-caption font-semibold text-fg-2 enabled:hover:text-fg-1 ${ROW.group}`}
    >
      {canFold ? <Icon name={s.folded ? "chevron-right" : "chevron-down"} size={14} className="text-fg-3" /> : <span className="w-3.5" />}
      <span className="truncate">{s.group || "Other tasks"}</span>
      <span className="font-normal text-fg-3 tabular-nums">{s.tasks.length}</span>
      <span className="ml-auto flex items-center gap-1.5">
        {s.running > 0 && <Badge tone="live">{s.running}<span className="hidden sm:inline"> running</span></Badge>}
        {s.failing > 0 && <Badge tone="fail">{s.failing}<span className="hidden sm:inline"> {s.failing === 1 ? "problem" : "problems"}</span></Badge>}
        {s.folded && s.disabled > 0 && <Badge tone="idle">{s.disabled} off</Badge>}
      </span>
    </button>
  );
}

/**
 * The list's own controls live in its header (two rows: ROW.bar + ROW.head, the
 * same heights as the timeline's controls + axis, so the rows below line up).
 * Phone: the column is narrow, so search is an icon that opens the field over the title.
 */
function ColumnHead(p: TaskColumnProps) {
  const [open, setOpen] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  // the field is always mounted (shown by CSS on sm+), so autoFocus would not fire: focus on open
  useEffect(() => {
    if (open) input.current?.focus();
  }, [open]);
  const searching = open || p.query !== "";
  return (
    <div>
      <div className={`relative flex items-center gap-2 px-3 ${ROW.bar}`}>
        <span className={`min-w-0 shrink-0 truncate text-caption font-semibold uppercase tracking-wider text-fg-3 ${searching ? "hidden sm:block" : ""}`}>
          Tasks{" "}
          {/* an invisible "N of N" holds the widest count, so a search never resizes the field next to it */}
          <span className="inline-grid font-normal normal-case tracking-normal tabular-nums">
            <span className="[grid-area:1/1]">· {p.shown === p.total ? p.total : `${p.shown} of ${p.total}`}</span>
            <span aria-hidden className="invisible [grid-area:1/1]">· {p.total} of {p.total}</span>
          </span>
        </span>
        <span className={`min-w-0 flex-1 sm:ml-auto sm:block sm:max-w-44 ${searching ? "block" : "hidden"}`}>
          <SearchField size="sm" value={p.query} onChange={p.onQuery} placeholder="Search" label="Search tasks" ref={input} onBlur={() => setOpen(false)} />
        </span>
        {!searching && (
          <span className="ml-auto sm:hidden">
            <IconButton size="sm" icon="search" label="Search tasks" onClick={() => setOpen(true)} />
          </span>
        )}
      </div>
      <div className={`flex items-center px-2 sm:px-3 ${ROW.head}`}>
        <FilterBar filter={p.filter} onFilter={p.onFilter} counts={p.counts} />
      </div>
    </div>
  );
}
