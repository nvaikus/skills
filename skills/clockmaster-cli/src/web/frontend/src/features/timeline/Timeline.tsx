import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import type { Lane, LaneRun } from "../../lib/types";
import { PRESETS, fetchWindow, thinOut, matchPreset, pan, presetView, ticks, xOf, zoom, type View } from "../../lib/timeline";
import { duration, when } from "../../lib/format";
import { runTip, runTone } from "../../lib/status";
import { useTimeline } from "../../data/hooks";
import { capturePointer, observeWidth, onWheel } from "../../platform/web/dom";
import { Segmented } from "../../ui/Segmented";
import { Button, IconButton } from "../../ui/Button";
import { ErrorText } from "../../ui/Feedback";
import { COL_W, ROW } from "../../ui/board";
import { toneBg } from "../../ui/tone";
import { tip } from "../../ui/Tooltip";

export type TimelineRow = { kind: "group"; group: string; folded: boolean } | { kind: "task"; name: string; enabled: boolean };

const DRAG_PX = 3;

/**
 * The visible window, owned above the lanes so it survives a task being opened
 * (the lanes unmount) and closed again. Preset views slide with "now".
 */
export function useTimelineView(now: number, fit: number | null) {
  const [view, setView] = useState<View>(() => presetView(24 * 3600e3, Date.now()));
  const [follow, setFollow] = useState(true);
  // first data: widen to a span where every task shows a run, unless the user already moved
  const fitted = useRef(false);
  useEffect(() => {
    if (fit == null || fitted.current) return;
    fitted.current = true;
    setView((cur) => (cur.to - cur.from === 24 * 3600e3 ? presetView(fit, Date.now()) : cur));
  }, [fit]);
  const v = follow ? presetView(view.to - view.from, now) : view;
  const set = useCallback((next: View) => {
    fitted.current = true;
    setFollow(false);
    setView(next);
  }, []);
  const toPreset = (span: number) => {
    fitted.current = true;
    setView(presetView(span, now));
    setFollow(true);
  };
  return { v, follow, now, set, toPreset, preset: follow ? matchPreset(v, now) : null, backToNow: () => toPreset(view.to - view.from) };
}
export type TimelineView = ReturnType<typeof useTimelineView>;

/** Range presets + zoom buttons + "Back to now"; sits in the board toolbar. */
export function TimelineControls({ tv }: { tv: TimelineView }) {
  const { v, now } = tv;
  const nowX = Math.min(1, Math.max(0, xOf(v, now)));
  return (
    <div className="flex items-center gap-1.5">
      {!tv.follow && (
        <Button size="sm" variant="ghost" icon="clock" onClick={tv.backToNow}>
          Now
        </Button>
      )}
      <Segmented
        size="sm"
        label="Time range"
        options={PRESETS.map((p) => ({ value: p.id, label: p.label }))}
        value={tv.preset}
        onChange={(id) => tv.toPreset(PRESETS.find((p) => p.id === id)!.span)}
      />
      <span className="hidden items-center sm:flex">
        <IconButton size="sm" icon="minus" label="Zoom out" onClick={() => tv.set(zoom(v, 1 / 0.7, nowX))} />
        <IconButton size="sm" icon="plus" label="Zoom in" onClick={() => tv.set(zoom(v, 0.7, nowX))} />
      </span>
    </div>
  );
}

/** Right side of the board: the time axis, then one lane per row of the task column. */
export function TimelineLanes({ rows, minBody, tv, onOpenRun, hover, onHover }: { rows: TimelineRow[]; /** px kept for the rows so a search/filter never moves the card */ minBody: number; tv: TimelineView; onOpenRun: (task: string, runId: string) => void; hover: string | null; onHover: (task: string | null) => void }) {
  const { v, now, set } = tv;
  const [width, setWidth] = useState(0);
  const win = fetchWindow(v);
  const { data, error } = useTimeline(win.from, win.to, rows.length > 0);
  const lanes = useMemo(() => new Map((data ?? []).map((l) => [l.task, l])), [data]);
  const tk = useMemo(() => (width ? ticks(v, width, width < 320 ? 64 : 84) : []), [v.from, v.to, width]); // eslint-disable-line react-hooks/exhaustive-deps

  // callback refs: the plot may mount late, so effects on a useRef would miss it
  const measureOff = useRef<() => void>(() => {});
  const axisRef = useCallback((el: HTMLDivElement | null) => {
    measureOff.current();
    measureOff.current = el ? observeWidth(el, setWidth) : () => {};
  }, []);

  const vRef = useRef(v);
  vRef.current = v;
  const wheelOff = useRef<() => void>(() => {});
  const plotRef = useCallback(
    (el: HTMLDivElement | null) => {
      wheelOff.current();
      wheelOff.current = el
        ? onWheel(el, (e) => {
            const rect = el.getBoundingClientRect();
            const w = rect.width;
            if (!w) return;
            const at = Math.min(1, Math.max(0, (e.clientX - rect.left) / w));
            const span = vRef.current.to - vRef.current.from;
            e.preventDefault();
            // line-mode wheels (Firefox) report lines, not pixels
            const k = e.deltaMode === 1 ? 16 : 1;
            if (e.shiftKey || Math.abs(e.deltaX) > Math.abs(e.deltaY)) {
              // horizontal trackpad swipe or Shift + wheel: pan
              const d = (e.shiftKey && !e.deltaX ? e.deltaY : e.deltaX) * k;
              set(pan(vRef.current, (d / w) * span));
            } else if (e.deltaY) {
              // plain wheel / vertical swipe / pinch (ctrl+wheel): zoom at the cursor
              set(zoom(vRef.current, Math.exp(e.deltaY * k * (e.ctrlKey ? 0.01 : 0.002)), at));
            }
          })
        : () => {};
    },
    [set],
  );

  // one pointer drags to pan (capture only after DRAG_PX so a click on a run still opens it);
  // two touch pointers pinch-zoom the time axis at their midpoint. The plot is touch-pan-y:
  // the browser keeps vertical page scroll, horizontal pan and pinch come here.
  const drag = useRef<{ x: number; id: number; v: View; moved: boolean } | null>(null);
  const pts = useRef(new Map<number, { x: number; y: number }>());
  const pinch = useRef<{ d: number; mid: number; at: number; v: View } | null>(null);
  const pinchState = () => {
    const [a, b] = [...pts.current.values()];
    return { d: Math.max(10, Math.hypot(a.x - b.x, a.y - b.y)), mid: (a.x + b.x) / 2 };
  };
  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    if (e.pointerType === "touch") pts.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pts.current.size === 2) {
      const rect = e.currentTarget.getBoundingClientRect();
      if (!rect.width) return;
      const { d, mid } = pinchState();
      pinch.current = { d, mid, at: Math.min(1, Math.max(0, (mid - rect.left) / rect.width)), v };
      drag.current = null;
      for (const id of pts.current.keys()) capturePointer(e.currentTarget, id);
      return;
    }
    if (e.button !== 0 || pinch.current) return;
    drag.current = { x: e.clientX, id: e.pointerId, v, moved: false };
  };
  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    if (pts.current.has(e.pointerId)) pts.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    const p = pinch.current;
    if (p) {
      if (pts.current.size < 2 || !width) return;
      const { d, mid } = pinchState();
      const z = zoom(p.v, p.d / d, p.at);
      set(pan(z, ((p.mid - mid) / width) * (z.to - z.from)));
      return;
    }
    const dr = drag.current;
    if (!dr || !width || dr.id !== e.pointerId) return;
    const dx = e.clientX - dr.x;
    if (!dr.moved) {
      if (Math.abs(dx) < DRAG_PX) return;
      dr.moved = true;
      capturePointer(e.currentTarget, dr.id);
    }
    set(pan(dr.v, (-dx / width) * (dr.v.to - dr.v.from)));
  };
  const onPointerUp = (e: PointerEvent<HTMLDivElement>) => {
    pts.current.delete(e.pointerId);
    if (pts.current.size < 2) pinch.current = null;
    const dr = drag.current;
    drag.current = null;
    if (dr?.moved) e.preventDefault();
  };
  const wasDrag = () => drag.current?.moved ?? false;

  const onKeyDown = (e: KeyboardEvent) => {
    const span = v.to - v.from;
    if (e.key === "ArrowLeft") set(pan(v, -span / 8));
    else if (e.key === "ArrowRight") set(pan(v, span / 8));
    else if (e.key === "+" || e.key === "=") set(zoom(v, 0.7, xOf(v, now)));
    else if (e.key === "-") set(zoom(v, 1 / 0.7, xOf(v, now)));
    else return;
    e.preventDefault();
  };

  const nowX = xOf(v, now);

  return (
    <div
      ref={plotRef}
      tabIndex={0}
      role="group"
      aria-label="Run timeline. Arrow keys pan, plus and minus zoom."
      onKeyDown={onKeyDown}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={(e) => {
        pts.current.delete(e.pointerId);
        if (pts.current.size < 2) pinch.current = null;
        drag.current = null;
      }}
      className="relative min-w-0 cursor-grab touch-pan-y select-none outline-offset-[-2px] active:cursor-grabbing"
    >
      {/* axis */}
      <div ref={axisRef} className={`relative overflow-hidden ${ROW.head}`}>
        {tk
          .filter((t) => {
            const px = xOf(v, t.t) * width;
            return px > 22 && px < width - 22;
          })
          .map((t) => (
            <span
              key={t.t}
              className={`absolute top-3 -translate-x-1/2 whitespace-nowrap text-micro tabular-nums ${t.major ? "font-semibold text-fg-2" : "text-fg-3"}`}
              style={{ left: `${xOf(v, t.t) * 100}%` }}
            >
              {t.label}
            </span>
          ))}
        {nowX >= 0 && nowX <= 1 && <span className="absolute bottom-0 h-2 w-px bg-accent" style={{ left: `${nowX * 100}%` }} />}
        {error && !data && (
          <div className="absolute inset-0 flex items-center bg-well px-3">
            <ErrorText inline>{error}</ErrorText>
          </div>
        )}
      </div>
      {/* lanes, one per row of the task column; no rows = an empty well of the same height */}
      <div className="relative" style={{ minHeight: minBody }}>
      {!rows.length && <Grid v={v} ticks={tk} nowX={nowX} />}
      {rows.map((r) =>
        r.kind === "group" ? (
          <div key={"g:" + r.group} className={`relative bg-fg-1/[0.025] ${ROW.group}`}>
            <Grid v={v} ticks={tk} nowX={nowX} />
          </div>
        ) : (
          <LaneRow key={r.name} hovered={hover === r.name} onHover={(on) => onHover(on ? r.name : null)} enabled={r.enabled} lane={lanes.get(r.name)} v={v} ticks={tk} nowX={nowX} now={now} width={width} onOpen={(id) => !wasDrag() && onOpenRun(r.name, id)} />
        ),
      )}
      </div>
    </div>
  );
}

/** Footer: gesture hint under the task column, colour key under the lanes (right-aligned). */
export function TimelineLegend() {
  return (
    <div className="flex items-start py-2 text-micro text-fg-3">
      {/* touch has its own gestures: the spacer stays, the mouse hint does not */}
      <div className={`${COL_W} px-4`}><span className="hidden md:inline">Scroll to zoom · drag or Shift + scroll to move</span></div>
      <div className="flex min-w-0 flex-1 flex-wrap items-center justify-end gap-x-4 gap-y-1 px-4">
        <Legend cls="bg-ok" label="Succeeded" />
        <Legend cls="bg-fail" label="Failed" />
        <Legend cls="bg-live" label="Running" />
        <Legend cls={QUEUED} label="Queued" />
        <Legend cls="bg-warn" label="Stopped, skipped" />
        <Legend cls={PLANNED} label="Planned" />
      </div>
    </div>
  );
}

function Legend({ cls, label }: { cls: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`h-2 w-3 rounded-sm ${cls}`} /> {label}
    </span>
  );
}

function Grid({ v, ticks: tk, nowX }: { v: View; ticks: { t: number; major: boolean }[]; nowX: number }) {
  return (
    <div className="pointer-events-none absolute inset-0">
      {tk.map((t) => (
        <span key={t.t} className={`absolute inset-y-0 w-px ${t.major ? "bg-fg-3/25" : "bg-line"}`} style={{ left: `${xOf(v, t.t) * 100}%` }} />
      ))}
      {nowX >= 0 && nowX <= 1 && <span className="absolute inset-y-0 w-px bg-accent/70" style={{ left: `${nowX * 100}%` }} />}
    </div>
  );
}

function LaneRow({ hovered, onHover, enabled, lane, v, ticks: tk, nowX, now, width, onOpen }: { hovered: boolean; onHover: (on: boolean) => void; enabled: boolean; lane: Lane | undefined; v: View; ticks: { t: number; major: boolean }[]; nowX: number; now: number; width: number; onOpen: (runId: string) => void }) {
  const span = v.to - v.from;
  const planned = (lane?.planned ?? []).map(Date.parse).filter((t) => t >= v.from && t <= v.to && t > now);
  // a planned pill is as wide as the task's typical run (same 3px floor as runs)
  const avg = lane?.avgDurationSec ?? null;
  const pillPx = Math.max(MIN_MARK_PX, width > 0 ? ((avg ?? 0) * 1000 * width) / span : 0);
  const k = thinOut(planned, pillPx + PLANNED_GAP_PX, width / span);
  const shown = k > 1 ? planned.filter((_, i) => i % k === 0) : planned;
  const every = k * (lane?.plannedEvery ?? 1);
  const typical = avg != null ? ` · ~${duration(avg)} typical` : "";
  return (
    <div onPointerEnter={() => onHover(true)} onPointerLeave={() => onHover(false)} className={`relative transition-colors ${ROW.task} ${hovered ? "bg-accent/5" : ""} ${enabled ? "" : "opacity-60"}`}>
      <Grid v={v} ticks={tk} nowX={nowX} />
      <div className="relative h-full overflow-hidden">
        {shown.map((t) => (
          <span key={t} {...tip(`Planned · ${when(new Date(t).toISOString(), now)}${typical}${every > 1 ? ` (1 of every ${every} shown)` : ""}`)} className={`absolute top-1/2 h-4 -translate-y-1/2 rounded-[3px] before:absolute before:-inset-x-1 before:-inset-y-1 before:content-[''] ${PLANNED}`} style={{ left: `${xOf(v, t) * 100}%`, width: pillPx }} />
        ))}
        {(lane?.runs ?? []).map((r) => (
          <RunMark key={r.runId} run={r} v={v} span={span} width={width} now={now} onOpen={() => onOpen(r.runId)} />
        ))}
      </div>
    </div>
  );
}

function RunMark({ run, v, span, width, now, onOpen }: { run: LaneRun; v: View; span: number; width: number; now: number; onOpen: () => void }) {
  const queued = run.status === "queued";
  const s = Date.parse(run.start);
  const e = run.end ? Date.parse(run.end) : run.status === "running" ? now : s + (run.durationSec ?? 0) * 1000;
  // the wait before the run: queuedAt -> start (a queued run waits until now)
  const q = run.queuedAt ? Date.parse(run.queuedAt) : s;
  const qEnd = queued ? now : s;
  if ((queued ? qEnd : e) < v.from || Math.min(q, s) > v.to) return null;
  const left = xOf(v, s);
  // real duration at this scale; a floor of 3px only for runs shorter than that
  const w = Math.max(width ? MIN_MARK_PX / width : 0.003, (e - s) / span);
  const tone = runTone(run.status);
  const label = runTip(run, now);
  const wait = qEnd > q && (
    <span
      {...(queued ? {} : tip(label))}
      onClick={onOpen}
      className={`absolute top-1/2 h-2.5 -translate-y-1/2 cursor-pointer rounded-l-[3px] ${QUEUED} ${queued ? "rounded-r-[3px]" : ""}`}
      style={{ left: `${xOf(v, q) * 100}%`, width: `${((qEnd - q) / span) * 100}%` }}
    />
  );
  if (queued)
    return (
      <button
        type="button"
        {...tip(label)}
        aria-label={label}
        onClick={onOpen}
        className={`absolute top-1/2 h-2.5 -translate-y-1/2 rounded-[3px] transition hover:brightness-110 hover:ring-2 hover:ring-fg-1/20 ${QUEUED}`}
        style={{ left: `${xOf(v, q) * 100}%`, width: `${Math.max(width ? 3 / width : 0.003, (qEnd - q) / span) * 100}%` }}
      />
    );
  return (
    <>
    {wait}
    <button
      type="button"
      {...tip(label)}
      aria-label={label}
      onClick={onOpen}
      className={`absolute top-1/2 h-4 -translate-y-1/2 rounded-[3px] transition hover:brightness-110 hover:ring-2 hover:ring-fg-1/20 ${toneBg[tone]} ${run.status === "running" ? "animate-beat" : ""} ${tone === "fail" ? "h-5" : ""}`}
      style={{ left: `${left * 100}%`, width: `${w * 100}%` }}
    />
    </>
  );
}

/** Waiting in the queue: a hatched violet band, lower than a run bar, drawn above overlapping runs. */
const QUEUED = "z-[1] bg-[repeating-linear-gradient(135deg,var(--color-queue)_0_2px,var(--color-surface)_2px_5px)] ring-1 ring-inset ring-queue/70";

/** Planned (future) run: a solid neutral pill, no outline, no status colour. */
const PLANNED = "bg-planned";

/** Narrowest run or planned mark, px. */
const MIN_MARK_PX = 3;
/** Clear space kept between neighbouring planned pills, px: they never merge into a bar. */
const PLANNED_GAP_PX = 2;

