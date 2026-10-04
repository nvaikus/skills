import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import { useOverlayGuard } from "../ui/overlay";
import type { EditForm, Run, Task, TaskDetail } from "../lib/types";
import { FILTERS, filterCounts, sectionsOf, type TaskFilter } from "../lib/groups";
import { useApp, useNotifyClick, useDrift, useNow, useRunSearch, useTasks } from "../data/hooks";
import { setEnabled, syncAll } from "../data/actions";
import { peek, seed } from "../data/store";
import { errorText } from "../data/api";
import { hasTextSelection, isBelow, onEscapeIdle, scrollToY, scrollY, setTitle } from "../platform/web/dom";
import { Card } from "../ui/Card";
import { Notice } from "../ui/Feedback";
import { COL_W, MIN_BODY_PX, ROW, ROW_PX } from "../ui/board";
import { useToast } from "../ui/Toast";
import { TaskColumn } from "../features/dashboard/TaskList";
import { TimelineControls, TimelineLanes, TimelineLegend, useTimelineView, type TimelineRow } from "../features/timeline/Timeline";
import { fitSpan } from "../lib/timeline";
import { TaskPage } from "../features/task/TaskPage";
import { EditDialog } from "../features/editor/EditDialog";
import { DeleteDialog } from "../features/editor/DeleteDialog";
import { Header } from "./Header";
import { useRoute } from "./useRoute";
import { useTheme } from "./useTheme";
import { useFolds, useStored } from "./usePrefs";

const FILTER_VALUES = FILTERS.map((f) => f.value);
/** Below Tailwind's lg the task detail replaces the whole screen. */
const WIDE_PX = 1024;

type Modal = { kind: "edit" | "delete"; task: TaskDetail; focus?: keyof EditForm } | null;

export function App() {
  const app = useApp();
  const { route, go } = useRoute();
  const theme = useTheme();
  const now = useNow(1000);
  const toast = useToast();
  const tasks = useTasks();
  const drift = useDrift();
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useStored<TaskFilter>("filter", "all", FILTER_VALUES);
  const folds = useFolds();
  const tv = useTimelineView(now, tasks.data ? fitSpan(tasks.data, now) : null);
  const [hover, setHover] = useState<string | null>(null);
  const [modal, setModal] = useState<Modal>(null);
  const [syncing, setSyncing] = useState(false);

  const title = app.data?.app ?? "clockmaster";
  const current = route.kind === "task" ? route.task : null;
  useEffect(() => setTitle(current ? `${current} · ${title}` : title), [current, title]);

  const list = tasks.data ?? [];
  const sections = useMemo(() => sectionsOf(list, query, filter, folds.folded), [list, query, filter, folds.folded]);
  const counts = useMemo(() => filterCounts(list), [list]);
  const shown = sections.reduce((n, s) => n + s.tasks.length, 0);
  const runHits = useRunSearch(query);

  // Arriving at a task inside a folded group unfolds it ONCE (the group can be
  // folded again by hand while that task stays current).
  const revealed = useRef<string | null>(null);
  useEffect(() => {
    if (!current || revealed.current === current) return;
    const t = list.find((x) => x.name === current);
    if (!t) return;
    revealed.current = current;
    if (t.group) folds.unfold(t.group);
  }, [current, list, folds]);

  // Phone: the detail replaces the screen; open at its top, return to where the list was.
  const listY = useRef(0);
  const prevCurrent = useRef(current);
  useEffect(() => {
    const was = prevCurrent.current;
    prevCurrent.current = current;
    if (!isBelow(WIDE_PX) || !!was === !!current) return;
    scrollToY(current ? 0 : listY.current);
  }, [current]);

  const openTask = useCallback(
    (name: string, runId: string | null = null) => {
      if (route.kind === "home") listY.current = scrollY();
      go({ kind: "task", task: name, runId });
    },
    [go, route.kind],
  );
  const close = useCallback(() => go({ kind: "home" }), [go]);
  useNotifyClick(openTask);
  useEffect(() => (current && !modal ? onEscapeIdle(close) : undefined), [current, modal, close]);
  // lg+: a plain click on empty page background (elements marked data-bg) closes the task, like Back.
  // Not on phone (detail is full screen), not after a text-selection drag, not when an overlay ate the press.
  const overlayAte = useOverlayGuard();
  const onBackgroundClick = (e: MouseEvent<HTMLElement>) => {
    if (!current || modal || isBelow(WIDE_PX)) return;
    if (!(e.target as HTMLElement).hasAttribute?.("data-bg") || overlayAte() || hasTextSelection()) return;
    close();
  };

  // clicking the open task again closes it (back to the timeline)
  const toggleTask = (name: string) => (name === current ? close() : openTask(name));

  const timelineRows = useMemo<TimelineRow[]>(() => {
    const grouped = sections.some((s) => s.group !== "");
    return sections.flatMap((s) => [
      ...(grouped ? [{ kind: "group" as const, group: s.group, folded: s.folded }] : []),
      ...(s.folded ? [] : s.tasks.map((t) => ({ kind: "task" as const, name: t.name, enabled: t.enabled }))),
    ]);
  }, [sections]);
  // Lanes stay while a search/filter matches nothing: the board keeps its two columns.
  const showLanes = !current && list.length > 0 && !tasks.pending;
  // Rows' height with no search/filter (folds count): both sides keep it as a min-height,
  // so typing a search or switching All/On/Off only adds and removes rows, nothing else moves.
  const minBody = useMemo(() => {
    const all = sectionsOf(list, "", "all", folds.folded);
    const grouped = all.some((s) => s.group !== "");
    const px = all.reduce((h, s) => h + (grouped ? ROW_PX.group : 0) + (s.folded ? 0 : s.tasks.length * ROW_PX.task), 0);
    return Math.max(MIN_BODY_PX, px);
  }, [list, folds.folded]);
  const clearSearch = () => {
    setQuery("");
    setFilter("all");
  };

  const doSync = async () => {
    setSyncing(true);
    try {
      const r = await syncAll();
      toast("ok", "Synced with the system scheduler", r.output);
    } catch (e) {
      toast("error", "Sync failed", errorText(e));
    } finally {
      setSyncing(false);
    }
  };

  const toggleEnabled = (t: Task, on: boolean) =>
    void setEnabled(t.name, on).then(
      () => toast("ok", `${t.name} is ${on ? "on" : "off"}`),
      (e) => toast("error", `Couldn't turn ${t.name} ${on ? "on" : "off"}`, errorText(e)),
    );

  const onRenamed = (oldName: string, newName: string) => {
    setModal(null);
    if (oldName === newName) return;
    // seed the new keys from the old cache so the page never flashes "no task"
    const old = peek<TaskDetail>(`task:${oldName}`);
    if (old) seed(`task:${newName}`, { ...old, name: newName });
    const runs = peek<Run[]>(`runs:${oldName}`);
    if (runs) seed(`runs:${newName}`, runs.map((r) => ({ ...r, task: newName })));
    revealed.current = newName;
    go({ kind: "task", task: newName, runId: route.kind === "task" ? route.runId : null }, "replace");
  };

  const notes = app.data?.notes ?? [];

  return (
    // a task open on lg+: the page is exactly one screen tall, its runs area fills down to the bottom
    <div className={`flex min-h-full flex-col ${current ? "lg:h-dvh" : ""}`}>
      <Header
        title={title}
        drift={drift.data?.drift ?? 0}
        syncing={syncing}
        onSync={doSync}
        theme={theme.pref}
        dark={theme.dark}
        onTheme={theme.setPref}
        onHome={close}
      />
      <main data-bg onClick={onBackgroundClick} className={`flex w-full flex-1 flex-col gap-4 px-3 pt-4 pb-16 sm:px-6 sm:pt-5 lg:px-8 ${current ? "lg:min-h-0 lg:pb-6" : ""}`}>
        <div data-bg className={`flex gap-5 ${current ? "items-start lg:min-h-0 lg:flex-1 lg:items-stretch" : "items-start"}`}>
          {/* the board: task column (+ lanes while no task is open) */}
          <div data-bg className={current ? "hidden w-72 shrink-0 rounded-2xl lg:block lg:overflow-y-auto" : "min-w-0 flex-1"}>
            <Card pad={false}>
              <div className="flex">
                <div className={showLanes ? `${COL_W} border-r border-line` : "min-w-0 flex-1"}>
                  <TaskColumn
                    sections={sections}
                    total={list.length}
                    shown={shown}
                    loading={tasks.pending}
                    error={tasks.error}
                    onFold={folds.toggle}
                    onOpen={toggleTask}
                    onOpenRun={(t, r) => openTask(t, r)}
                    now={now}
                    onEnabled={toggleEnabled}
                    current={current}
                    hover={hover}
                    onHover={setHover}
                    filter={filter}
                    onFilter={setFilter}
                    counts={counts}
                    query={query}
                    onQuery={setQuery}
                    minBody={minBody}
                    onClear={clearSearch}
                    runs={runHits}
                  />
                </div>
                {showLanes && (
                  <div className="min-w-0 flex-1 bg-well shadow-[inset_3px_0_5px_-3px_var(--color-well-shade)]">
                    <div className={`flex items-center justify-end px-2 ${ROW.bar}`}>
                      <TimelineControls tv={tv} />
                    </div>
                    <TimelineLanes rows={timelineRows} minBody={minBody} tv={tv} onOpenRun={(t, r) => openTask(t, r)} hover={hover} onHover={setHover} />
                  </div>
                )}
              </div>
              {showLanes && <TimelineLegend />}
            </Card>
          </div>
          {route.kind === "task" && (
            <div className="min-w-0 flex-1 lg:flex lg:min-h-0 lg:flex-col">
              <TaskPage
                key={route.task}
                name={route.task}
                runId={route.runId}
                app={app.data}
                now={now}
                onBack={close}
                onSelectRun={(id) => go({ kind: "task", task: route.task, runId: id }, "replace")}
                onCloseRun={() => go({ kind: "task", task: route.task, runId: null }, "replace")}
                onEdit={(t, focus) => setModal({ kind: "edit", task: t, focus })}
                onDelete={(t) => setModal({ kind: "delete", task: t })}
              />
            </div>
          )}
        </div>

        {notes.length > 0 && !current && (
          <div className="flex flex-col gap-2">
            {notes.map((n, i) => (
              <Notice key={i}>{n}</Notice>
            ))}
          </div>
        )}
      </main>
      {modal?.kind === "edit" && <EditDialog key={"e:" + modal.task.name} task={modal.task} focus={modal.focus} onClose={() => setModal(null)} onSaved={onRenamed} />}
      {modal?.kind === "delete" && (
        <DeleteDialog
          key={"d:" + modal.task.name}
          task={modal.task}
          onClose={() => setModal(null)}
          onDeleted={() => {
            setModal(null);
            go({ kind: "home" }, "replace");
          }}
        />
      )}
    </div>
  );
}
