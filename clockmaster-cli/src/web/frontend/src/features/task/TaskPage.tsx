import { useState } from "react";
import type { AppInfo, EditForm, Notify, Run, TaskDetail } from "../../lib/types";
import { sentence, timeoutText, until, usd } from "../../lib/format";
import { NOTIFY_OPTIONS, stateNote } from "../../lib/status";
import { useRuns, useTask } from "../../data/hooks";
import { runNow, setEnabled, setNotify, setSound, syncAll } from "../../data/actions";
import { errorText } from "../../data/api";
import { Button, IconButton } from "../../ui/Button";
import { Card } from "../../ui/Card";
import { Meta } from "../../ui/Meta";
import { EmptyState, ErrorText, Loading, Notice } from "../../ui/Feedback";
import { Icon } from "../../ui/Icon";
import { MenuDivider, MenuItem, Popover } from "../../ui/Popover";
import { Segmented } from "../../ui/Segmented";
import { Badge } from "../../ui/Status";
import { Switch } from "../../ui/Switch";
import { copyText } from "../../platform/web/dom";
import { useToast } from "../../ui/Toast";
import { RunList } from "./RunList";
import { RunPanel } from "./RunPanel";
import { tipIfCut } from "../../ui/Tooltip";

export interface TaskPageProps {
  name: string;
  runId: string | null;
  app: AppInfo | null;
  now: number;
  onBack: () => void;
  onSelectRun: (runId: string) => void;
  onCloseRun: () => void;
  onEdit: (t: TaskDetail, field?: keyof EditForm) => void;
  onDelete: (t: TaskDetail) => void;
}

export function TaskPage(p: TaskPageProps) {
  const task = useTask(p.name);
  const t = task.data;
  const anyRunning = !!t?.lastRuns.some((r) => r.status === "running" || r.status === "queued");
  const runs = useRuns(p.name, anyRunning);
  const toast = useToast();
  const [starting, setStarting] = useState(false);
  const [copied, setCopied] = useState(false);

  if (!t) {
    if (task.error)
      return (
        <Card>
          <EmptyState icon="search" title={`No task named “${p.name}”`}>
            {task.error.includes("no task") || task.error.startsWith("404") ? "It may have been renamed or deleted." : task.error}
            <div className="mt-3">
              <Button size="sm" icon="chevron-left" onClick={p.onBack}>
                All tasks
              </Button>
            </div>
          </EmptyState>
        </Card>
      );
    return <Loading />;
  }

  const list = runs.data ?? [];
  const selected: Run | null = (p.runId ? list.find((r) => r.runId === p.runId) : list[0]) ?? null;
  const note = stateNote(t.state, t.enabled) ?? (t.drift ? "The system scheduler has a different copy of this task — sync to fix." : null);

  const run = async () => {
    setStarting(true);
    try {
      await runNow(t.name);
      toast("ok", `Started ${t.name}`);
    } catch (e) {
      toast("error", "Couldn't start the run", errorText(e));
    } finally {
      setTimeout(() => setStarting(false), 1200);
    }
  };
  const act = (fn: () => Promise<unknown>, fail: string) => () =>
    void fn().catch((e) => toast("error", fail, errorText(e)));

  const notifyChannels = p.app?.notifyChannels ?? [];
  const notifyWhen = t.notify === "off" ? "off" : t.notify === "on" ? "after every run" : "on failure";
  const unset = t.notify !== "off" && notifyChannels.length === 0;
  const notifyTo = t.notify === "off" ? "" : unset ? "not set up" : notifyChannels.join(", ");
  const notifyFile = p.app ? `${p.app.dataDir}/notify.yaml` : "notify.yaml";
  const copyCommand = async () => {
    if (await copyText(t.command)) {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }
  };
  const showSound = p.app?.platform === "darwin" && p.app.sounds.length > 0;

  return (
    <div className="@container flex flex-col gap-4 lg:min-h-0 lg:flex-1">
      <nav className="flex items-center gap-1 text-caption text-fg-3">
        <button type="button" onClick={p.onBack} className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 hover:bg-raised hover:text-fg-1">
          <Icon name="chevron-left" size={14} />
          <span className="lg:hidden">All tasks</span>
          <span className="hidden lg:inline">Back to timeline</span>
        </button>
        {t.group && (
          <>
            <span>/</span>
            <span className="px-1">{t.group}</span>
          </>
        )}
        <span className="ml-auto hidden lg:inline">Esc to close</span>
      </nav>

      {/* 1. header: who it is and what you can do */}
      <div className="flex flex-col gap-3 @xl:flex-row @xl:items-start">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="min-w-0 break-words text-display font-semibold tracking-tight">{t.name}</h1>
            {!t.enabled && <Badge tone="idle">Off</Badge>}
            {anyRunning && <Badge tone="live">Running</Badge>}
          </div>
          {t.description && (
            <p {...tipIfCut(t.description)} className="mt-0.5 line-clamp-2 text-body text-fg-3">
              {t.description}
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          <label className="mr-1 flex items-center gap-2 text-caption text-fg-2">
            <Switch checked={t.enabled} onChange={(on) => act(() => setEnabled(t.name, on), "Couldn't change the schedule")()} label={t.enabled ? "Turn schedule off" : "Turn schedule on"} />
            <span className="w-6">{t.enabled ? "On" : "Off"}</span>
          </label>
          <Button variant="primary" icon="play" busy={starting} onClick={run}>
            Run now
          </Button>
          <Popover
            trigger={({ open, toggle }) => <IconButton icon="more" label="More actions" active={open} onClick={toggle} aria-haspopup="menu" aria-expanded={open} />}
          >
            {(close) => (
              <>
                <MenuItem icon="edit" onSelect={() => (close(), p.onEdit(t))}>
                  Edit or rename…
                </MenuItem>
                <MenuDivider />
                <MenuItem icon="trash" danger onSelect={() => (close(), p.onDelete(t))}>
                  Delete…
                </MenuItem>
              </>
            )}
          </Popover>
        </div>
      </div>

      {note && (
        <Notice tone="warn">
          <div className="flex flex-wrap items-center gap-2">
            <span className="flex-1">{note}</span>
            <Button
              size="sm"
              icon="sync"
              onClick={act(async () => {
                const r = await syncAll();
                toast("ok", "Synced with the system scheduler", r.output);
              }, "Sync failed")}
            >
              Sync now
            </Button>
          </div>
        </Notice>
      )}

      {/* 2. settings at a glance: one inline meta row; a click edits that field */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1" aria-label="Settings">
        <Meta icon="clock" full={`${sentence(t.scheduleText || t.schedule)} (${t.schedule})`} onClick={() => p.onEdit(t, "schedule")} max="max-w-full">
          {sentence(t.scheduleText || t.schedule)} <span className="font-mono text-micro text-fg-3">({t.schedule})</span>
        </Meta>
        <Popover
          align="start"
          width="w-80"
          trigger={({ open, toggle }) => (
            <Meta icon="bell" label={t.notify === "off" ? "Notify:" : `Notify ${notifyWhen}`} tone={unset ? "warn" : undefined} onClick={toggle} expanded={open}>
              {t.notify === "off" ? "off" : `→ ${notifyTo}`}
            </Meta>
          )}
        >
          {() => (
            <div className="flex flex-col gap-2.5 p-2">
              <span className="text-caption font-medium text-fg-2">Notify me</span>
              <Segmented<Notify>
                size="sm"
                label="Notifications"
                options={NOTIFY_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
                value={t.notify}
                onChange={(n) => act(() => setNotify(t.name, n), "Couldn't change notifications")()}
              />
              {notifyChannels.length ? (
                <span className="text-caption text-fg-3">Sent to {notifyChannels.join(", ")}.</span>
              ) : (
                <div className="flex flex-col gap-1.5 text-caption text-fg-2">
                  <span className="font-medium text-warn">Nothing is delivered: no channel is set up.</span>
                  {p.app?.platform === "linux" && <span>This machine has no desktop banners, so Telegram is the way to get them.</span>}
                  <span>
                    Telegram (needs the claude-tg bot): add <code className="font-mono text-micro text-fg-1">telegram: on</code> to
                  </span>
                  <code className="break-all rounded-md bg-raised px-2 py-1 font-mono text-micro text-fg-1">{notifyFile}</code>
                  <span className="text-fg-3">Teams: teams_team + teams_channel in the same file. Takes effect on the next run.</span>
                </div>
              )}
              {showSound && <SoundPicker sounds={p.app!.sounds} value={t.sound} disabled={t.notify === "off"} onChange={(s) => act(() => setSound(t.name, s), "Couldn't change the sound")()} />}
            </div>
          )}
        </Popover>
        <Meta icon="timer" label="Timeout:" hint="A run is stopped if it takes longer" onClick={() => p.onEdit(t, "timeout")}>
          {t.timeoutSec ? timeoutText(t.timeoutSec) : "none"}
        </Meta>
        <Meta icon="play" label="Parallel:" hint={t.queue ? `More runs wait in a queue (max ${t.queue})` : "No queue: a run that finds no free slot is skipped"} onClick={() => p.onEdit(t, "parallel")}>
          {t.parallel > 1 ? `up to ${t.parallel} at a time` : "1 at a time"}
          {t.queued > 0 && <span className="text-queue"> · {t.queued} queued</span>}
        </Meta>
        <Meta icon="history" label="Keeps:" hint="Older run logs are deleted" onClick={() => p.onEdit(t, "keep")}>
          {t.keep == null ? "all runs" : `${t.keep} runs`}
        </Meta>
        <Meta icon="terminal" label="Runs:" full={copied ? undefined : t.command} onClick={copyCommand} max="max-w-80">
          <span className="font-mono text-micro">{copied ? "Copied" : t.command}</span>
        </Meta>
        <Meta icon="folder" label="In:" full={t.workdir} onClick={() => p.onEdit(t, "workdir")} max="max-w-64">
          <span className="font-mono text-micro">{t.workdir}</span>
        </Meta>
        <Meta icon="arrow" label="Next:">
          {t.enabled ? (t.nextRun ? until(t.nextRun, p.now) : "none") : "not scheduled"}
        </Meta>
        {t.spentUsd != null && (
          <Meta icon="spark" label="Spent:">
            {usd(t.spentUsd)}
          </Meta>
        )}
      </div>

      {/* 3. runs take the rest: list | selected run. Narrow: list, then a tapped run replaces it */}
      <div className="grid min-h-0 flex-1 gap-4 @4xl:grid-cols-[clamp(13.75rem,18cqw,16.25rem)_minmax(0,1fr)] @4xl:grid-rows-[minmax(0,1fr)]">
        <div className={`min-h-0 flex-col ${p.runId ? "hidden @4xl:flex" : "flex"}`}>
          <RunList runs={list} loading={runs.pending} error={runs.error} selected={selected?.runId ?? null} now={p.now} onSelect={p.onSelectRun} />
        </div>
        <div className={`min-h-0 flex-col ${p.runId ? "flex" : "hidden @4xl:flex"}`}>
          {selected ? (
            <RunPanel key={selected.runId} run={selected} app={p.app} now={p.now} onBack={p.onCloseRun} />
          ) : runs.error ? (
            <ErrorText>{runs.error}</ErrorText>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function SoundPicker({ sounds, value, disabled, onChange }: { sounds: string[]; value: string; disabled: boolean; onChange: (s: string) => void }) {
  const label = value === "off" ? "Silent" : value === "on" ? "Default sound" : value;
  return (
    <div className={`flex items-center gap-2.5 ${disabled ? "opacity-50" : ""}`}>
      <Popover
        align="start"
        width="w-52"
        trigger={({ open, toggle }) => (
          <Button size="sm" onClick={toggle} disabled={disabled} aria-haspopup="menu" aria-expanded={open}>
            {label} <Icon name="chevron-down" size={12} />
          </Button>
        )}
      >
        {(close) => (
          <div className="max-h-72 overflow-y-auto">
            <MenuItem checked={value === "off"} onSelect={() => (close(), onChange("off"))}>
              Silent
            </MenuItem>
            <MenuDivider />
            {sounds.map((s) => (
              <MenuItem key={s} checked={value === s} onSelect={() => (close(), onChange(s))}>
                {s}
              </MenuItem>
            ))}
          </div>
        )}
      </Popover>
    </div>
  );
}
