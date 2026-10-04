import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { portalRoot, viewportWidth, watchTips, type TipTarget } from "../platform/web/dom";

/**
 * Tooltip text for any element: spread `{...tip("…")}` instead of `title`.
 * Native `title` waits ~1s and never shows on touch or focus; the app tooltip
 * (TooltipLayer, mounted once) shows in ~100ms, follows the pointer, shows on
 * keyboard focus; on touch only on a long press. It is a description, not a name: icon-only
 * controls still need their own aria-label.
 */
export const tip = (text: string | null | undefined): { "data-tip"?: string } => (text ? { "data-tip": text } : {});

/**
 * The full text of a line that may be cut (ellipsis / line-clamp): the tooltip
 * shows only while the element or a child is actually truncated.
 */
export const tipIfCut = (text: string | null | undefined): { "data-tip"?: string; "data-tip-cut"?: "" } => (text ? { "data-tip": text, "data-tip-cut": "" } : {});

// Tooltips are for information that is not on screen: run marks, planned pills,
// warning icons, icon-only buttons, cut text, non-obvious settings. Never on a
// labelled button, a name, a badge with text or anything its label already says.

const GAP = 6;
const EDGE = 8;

/** The one floating tooltip for the page; mount once at the root. */
export function TooltipLayer() {
  const [t, setT] = useState<TipTarget | null>(null);
  const [pos, setPos] = useState<{ left: number; top: number; below: boolean } | null>(null);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => watchTips(setT), []);

  // screen readers: describe the target by the tooltip while it shows
  useEffect(() => {
    if (!t) return;
    const el = t.el;
    if (el.getAttribute("aria-label") === t.text) return;
    const prev = el.getAttribute("aria-describedby");
    el.setAttribute("aria-describedby", "app-tooltip");
    return () => (prev ? el.setAttribute("aria-describedby", prev) : el.removeAttribute("aria-describedby"));
  }, [t?.el, t?.text]); // eslint-disable-line react-hooks/exhaustive-deps

  useLayoutEffect(() => {
    if (!t || !box.current) return setPos(null);
    if (!t.el.isConnected) return setT(null);
    const r = t.el.getBoundingClientRect();
    const w = box.current.offsetWidth;
    const h = box.current.offsetHeight;
    const cx = t.x ?? r.left + r.width / 2;
    const left = Math.min(Math.max(cx - w / 2, EDGE), viewportWidth() - w - EDGE);
    const below = r.top - h - GAP < EDGE;
    setPos({ left, top: below ? r.bottom + GAP : r.top - h - GAP, below });
  }, [t]);

  if (!t) return null;
  return createPortal(
    <div
      ref={box}
      id="app-tooltip"
      role="tooltip"
      style={pos ? { left: pos.left, top: pos.top } : { left: 0, top: 0, visibility: "hidden" }}
      className="pointer-events-none fixed z-(--z-tip) max-w-72 rounded-md border border-tip-line bg-tip px-2 py-1 whitespace-pre-line text-caption text-on-tip shadow-lg [overflow-wrap:anywhere]"
    >
      {t.text}
    </div>,
    portalRoot(),
  );
}
