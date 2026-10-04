import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import type { AppInfo, Run } from "../../lib/types";
import { duration, usd, when } from "../../lib/format";
import { exitText, runLength, startedBy, waitedSec } from "../../lib/status";
import { resumeCommand } from "../../lib/claude";
import { useLog } from "../../data/hooks";
import { resumeRun, stopRun } from "../../data/actions";
import { errorText } from "../../data/api";
import { atBottom, scrollToBottom } from "../../platform/web/dom";
import { Button } from "../../ui/Button";
import { Card } from "../../ui/Card";
import { CodeLine } from "../../ui/Code";
import { ErrorText } from "../../ui/Feedback";
import { Icon, type IconName } from "../../ui/Icon";
import { RunBadge } from "../../ui/Status";
import { useToast } from "../../ui/Toast";

/** `onBack` (narrow screens only): back to the run list. */
export function RunPanel({ run, app, now, onBack }: { run: Run; app: AppInfo | null; now: number; onBack?: () => void }) {
  const queued = run.status === "queued";
  const live = run.status === "running" || queued;
  const log = useLog(run.task, run.runId, live);
  const waited = waitedSec(run, run.status, now);
  const toast = useToast();
  const [stopping, setStopping] = useState(false);
  const [resume, setResume] = useState<{ command: string; note?: string } | null>(null);
  const [resuming, setResuming] = useState(false);

  const stop = async () => {
    setStopping(true);
    try {
      const r = await stopRun(run.task, run.runId);
      toast("ok", queued ? "Removed from the queue" : "Run stopped", r.note);
    } catch (e) {
      toast("error", "Couldn't stop the run", errorText(e));
    } finally {
      setStopping(false);
    }
  };

  const canOpen = !!app?.canOpenTerminal;
  const getResume = async () => {
    setResuming(true);
    try {
      // where no terminal can be opened the server only returns the command (opened=false)
      const r = await resumeRun(run.task, run.runId);
      if (r.opened) toast("ok", "Opened the session in a terminal");
      else setResume({ command: r.command, note: r.note });
    } catch (e) {
      const fallback = resumeCommand(run);
      if (fallback) setResume({ command: fallback, note: errorText(e) });
      else toast("error", "Couldn't resume the session", errorText(e));
    } finally {
      setResuming(false);
    }
  };
  const localCmd = resumeCommand(run);

  return (
    <section aria-label="Selected run" className="flex min-h-0 min-w-0 flex-1 flex-col gap-2">
      <div className="flex min-h-9 items-center gap-2">
        {onBack && (
          <span className="@4xl:hidden">
            <Button size="sm" variant="ghost" icon="chevron-left" onClick={onBack}>
              All runs
            </Button>
          </span>
        )}
        <h2 className="text-caption font-semibold uppercase tracking-wider text-fg-3">Run</h2>
        <code className="truncate font-mono text-micro text-fg-3">{run.runId}</code>
      </div>
      <Card pad={false} fill>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line-soft px-4 py-3">
          <RunBadge status={run.status} />
          <Meta icon="clock">
            {queued ? `queued ${when(run.queuedAt ?? run.start, now)}` : when(run.start, now)}
          </Meta>
          <Meta icon="history">{run.status === "running" ? duration((now - Date.parse(run.start)) / 1000) : runLength(run, now)}</Meta>
          {!queued && waited >= 1 && <Meta icon="timer">waited {duration(waited)} in the queue</Meta>}
          <Meta icon={run.trigger === "manual" ? "play" : "timeline"}>{startedBy(run.trigger)}</Meta>
          {!live && run.status !== "skipped" && <Meta icon="info">{exitText(run.status, run.exitCode)}</Meta>}
          {run.costUsd != null && <span className="text-caption font-medium text-claude">{usd(run.costUsd)}</span>}
          <span className="ml-auto flex items-center gap-2">
            {live && (
              <Button size="sm" variant="danger" icon="stop" busy={stopping} onClick={stop}>
                {queued ? "Remove from queue" : "Stop"}
              </Button>
            )}
            {run.hasSession && (
              canOpen ? (
                <Button size="sm" icon="terminal" busy={resuming} onClick={getResume}>
                  Open in terminal
                </Button>
              ) : (
                <Button size="sm" icon="spark" busy={resuming} onClick={getResume}>
                  Resume session
                </Button>
              )
            )}
          </span>
        </div>
        {run.hasSession && (resume || (canOpen && localCmd)) && (
          <div className="flex flex-col gap-1.5 border-b border-line-soft px-4 py-3">
            <div className="text-caption text-fg-2">Continue this Claude conversation in a terminal:</div>
            <CodeLine text={resume?.command ?? localCmd!} label="Copy command" />
            {resume?.note && <div className="text-caption text-fg-3">{resume.note}</div>}
          </div>
        )}
        <LogView text={log.data} error={log.error} live={run.status === "running"} queued={queued} />
      </Card>
    </section>
  );
}

function Meta({ icon, children }: { icon: IconName; children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-caption text-fg-2">
      <Icon name={icon} size={13} className="text-fg-3" />
      {children}
    </span>
  );
}

/** Output pane; follows the tail while live unless the reader scrolled up. */
function LogView({ text, error, live, queued }: { text: string | null; error: string | null; live: boolean; queued: boolean }) {
  const el = useRef<HTMLPreElement | null>(null);
  const stick = useRef(true);
  const [follow, setFollow] = useState(true);
  const ref = useCallback((node: HTMLPreElement | null) => {
    el.current = node;
    if (node) scrollToBottom(node);
  }, []);
  useEffect(() => {
    if (el.current && stick.current) scrollToBottom(el.current);
  }, [text]);
  return (
    <div className="relative flex min-h-0 flex-1 flex-col">
      {error && !text ? (
        <div className="p-4">
          <ErrorText>{error}</ErrorText>
        </div>
      ) : (
        <pre
          ref={ref}
          tabIndex={0}
          aria-label="Run output"
          onScroll={(e) => {
            stick.current = atBottom(e.currentTarget);
            setFollow(stick.current);
          }}
          className="h-[26rem] min-h-0 overflow-auto whitespace-pre-wrap lg:h-auto lg:flex-1 break-words bg-sunken px-4 py-3 font-mono text-caption leading-5 text-fg-1"
        >
          {text == null ? <span className="text-fg-3">Loading output…</span> : text === "" ? <span className="text-fg-3">{queued ? "Waiting in the queue — output starts when the run does." : live ? "Waiting for output…" : "No output."}</span> : text}
        </pre>
      )}
      {live && (
        <div className="pointer-events-none absolute right-3 bottom-3 flex items-center gap-2">
          {!follow && (
            <button
              type="button"
              className="pointer-events-auto rounded-full border border-line bg-surface px-2.5 py-1 text-micro text-fg-2 shadow-sm hover:text-fg-1"
              onClick={() => {
                stick.current = true;
                setFollow(true);
                if (el.current) scrollToBottom(el.current);
              }}
            >
              Jump to latest
            </button>
          )}
          <span className="inline-flex items-center gap-1.5 rounded-full bg-live/12 px-2.5 py-1 text-micro font-semibold text-live">
            <span className="size-1.5 animate-beat rounded-full bg-live" /> Live
          </span>
        </div>
      )}
    </div>
  );
}
