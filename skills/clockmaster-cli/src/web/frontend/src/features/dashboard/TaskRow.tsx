import type { MouseEvent } from "react";
import type { Task } from "../../lib/types";
import { isFailure, runTone } from "../../lib/status";
import { Switch } from "../../ui/Switch";
import { Dot } from "../../ui/Status";
import { Icon } from "../../ui/Icon";
import { ROW } from "../../ui/board";
import { RunStrip } from "./RunStrip";
import { tip, tipIfCut } from "../../ui/Tooltip";

/** One task in the board's left column: status, name, plain-words schedule. */
export function TaskRow({ task: t, now, current, hovered, onHover, onOpen, onOpenRun, onEnabled }: { task: Task; now: number; current: boolean; hovered: boolean; onHover: (on: boolean) => void; onOpen: () => void; onOpenRun: (runId: string) => void; onEnabled: (on: boolean) => void }) {
  const last = t.lastRun;
  // the newest run may be a queued one; a run older than it can still be going
  const running = t.lastRuns.some((r) => r.status === "running");
  const failed = last != null && isFailure(last.status);
  const tone = running ? "live" : failed ? "fail" : !t.enabled ? "idle" : last ? runTone(last.status) : "idle";
  // a plain click selects in place; ctrl/cmd/middle click keeps "open in new tab"
  const onLink = (e: MouseEvent) => {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) e.stopPropagation();
    else e.preventDefault();
  };
  return (
    <li
      aria-current={current || undefined}
      onClick={onOpen}
      onPointerEnter={() => onHover(true)}
      onPointerLeave={() => onHover(false)}
      className={`relative flex cursor-pointer items-center gap-2.5 px-3 transition-colors ${ROW.task} ${
        current ? "bg-accent/10 shadow-[inset_3px_0_0_var(--color-accent)]" : hovered ? "bg-accent/5" : ""
      }`}
    >
      <Dot tone={tone} pulse={running} />
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-1.5">
          <a
            href={`#/${encodeURIComponent(t.name)}`}
            onClick={onLink}
            className={`truncate text-body font-medium outline-offset-1 ${t.enabled ? "text-fg-1" : "text-fg-3"}`}
          >
            {t.name}
          </a>
          {t.drift && (
            <span {...tip("Out of sync with the system scheduler")} aria-label="Out of sync with the system scheduler" className="shrink-0 text-warn">
              <Icon name="alert" size={13} />
            </span>
          )}
          <span className="ml-auto pl-1">
            <RunStrip runs={t.lastRuns} now={now} onOpen={onOpenRun} />
          </span>
        </div>
        {/* capitalised in JS: CSS ::first-letter sticks to the schedule text when a prefix span appears later ("ERunning now · very…") */}
        <div className="truncate text-caption text-fg-2" {...tipIfCut(t.scheduleText || t.schedule)}>
          {!t.enabled && <span className="font-medium text-fg-3">Off · </span>}
          {running ? <span className="text-live">Running now · </span> : null}
          {t.queued > 0 ? <span className="text-queue">{t.queued} queued · </span> : null}
          {!t.enabled || running || t.queued > 0 ? t.scheduleText || t.schedule : capitalize(t.scheduleText || t.schedule)}
        </div>
      </div>
      {/* phone: the column is narrow; the switch lives in the task detail there */}
      <span className="hidden sm:inline-flex">
        <Switch size="sm" checked={t.enabled} onChange={onEnabled} label={t.enabled ? `Turn ${t.name} off` : `Turn ${t.name} on`} />
      </span>
    </li>
  );
}

const capitalize = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
