// Small DOM adapters so views never reach for document/window directly.

export function setTitle(t: string): void {
  document.title = t;
}

export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // http on a non-localhost origin has no clipboard API: fall back to execCommand
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    ta.remove();
    return ok;
  }
}

/**
 * Escape is spent once: whoever handles it calls preventDefault on keydown AND
 * on the matching keyup — otherwise the browser also acts on it (Safari/macOS
 * leaves fullscreen). Overlays hear it first (capture), the page's fallback last.
 */
let escSpent = false;
const spendUp = (e: KeyboardEvent) => {
  if (e.key !== "Escape" || !escSpent) return;
  escSpent = false;
  e.preventDefault();
};
window.addEventListener("keyup", spendUp, true);

/** Escape in the CAPTURE phase on window: overlays win over inputs and bubble handlers. */
export function onEscape(cb: (e: KeyboardEvent) => void): () => void {
  const h = (e: KeyboardEvent) => {
    if (e.key !== "Escape") return;
    cb(e);
    if (e.defaultPrevented) escSpent = true;
  };
  window.addEventListener("keydown", h, true);
  return () => window.removeEventListener("keydown", h, true);
}

const busyTarget = (t: EventTarget | null) =>
  t instanceof Element && t.closest('input, textarea, select, [contenteditable=""], [contenteditable="true"], [role="dialog"]') !== null;

/**
 * Escape as a page fallback (BUBBLE phase): heard only when no overlay spent it
 * and focus is not in a field; spends it (keydown + keyup), fires once per press.
 */
export function onEscapeIdle(cb: () => void): () => void {
  const h = (e: KeyboardEvent) => {
    if (e.key !== "Escape" || e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
    if (e.defaultPrevented || busyTarget(e.target)) return;
    e.preventDefault();
    escSpent = true;
    if (!e.repeat) cb();
  };
  window.addEventListener("keydown", h);
  return () => window.removeEventListener("keydown", h);
}

export function onKey(cb: (e: KeyboardEvent) => void): () => void {
  window.addEventListener("keydown", cb);
  return () => window.removeEventListener("keydown", cb);
}

/** ResizeObserver on one element; returns the disconnect. */
export function observeWidth(el: Element, cb: (width: number) => void): () => void {
  const ro = new ResizeObserver((entries) => cb(entries[0].contentRect.width));
  ro.observe(el);
  return () => ro.disconnect();
}

/** Non-passive wheel listener (React's onWheel is passive and cannot preventDefault). */
export function onWheel(el: Element, cb: (e: WheelEvent) => void): () => void {
  const h = (e: Event) => cb(e as WheelEvent);
  el.addEventListener("wheel", h, { passive: false });
  return () => el.removeEventListener("wheel", h);
}

export function capturePointer(el: Element, pointerId: number): void {
  try {
    el.setPointerCapture(pointerId);
  } catch {
    /* pointer already gone */
  }
}

export function focusFirst(root: HTMLElement | null): void {
  const el =
    root?.querySelector<HTMLElement>("[data-autofocus]") ??
    root?.querySelector<HTMLElement>("input, textarea, select, button:not([disabled])");
  el?.focus();
}

export function activeElement(): HTMLElement | null {
  return document.activeElement as HTMLElement | null;
}

export function scrollIntoView(el: Element | null): void {
  el?.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

export function isNarrow(): boolean {
  return window.matchMedia("(max-width: 720px)").matches;
}

/** pointerdown anywhere (capture) — outside-click detection for popovers. */
export function onPointerDownAnywhere(cb: (target: Node | null) => void): () => void {
  const h = (e: PointerEvent) => cb(e.target as Node | null);
  window.addEventListener("pointerdown", h, true);
  return () => window.removeEventListener("pointerdown", h, true);
}

/** Keep Tab focus inside `root` (dialog focus trap). */
export function trapTab(e: KeyboardEvent, root: HTMLElement): void {
  if (e.key !== "Tab") return;
  const items = [...root.querySelectorAll<HTMLElement>('button:not([disabled]), [href], input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])')].filter(
    (el) => el.offsetParent !== null,
  );
  if (!items.length) return;
  const first = items[0];
  const last = items[items.length - 1];
  if (e.shiftKey && document.activeElement === first) {
    e.preventDefault();
    last.focus();
  } else if (!e.shiftKey && document.activeElement === last) {
    e.preventDefault();
    first.focus();
  }
}

export const atBottom = (el: HTMLElement, slack = 24) => el.scrollHeight - el.scrollTop - el.clientHeight <= slack;
export const scrollToBottom = (el: HTMLElement) => void (el.scrollTop = el.scrollHeight);

export function scrollY(): number {
  return window.scrollY;
}
export function scrollToY(y: number): void {
  window.scrollTo({ top: y });
}

/** Viewport narrower than `px` (layout switches; matches Tailwind's breakpoints). */
export function isBelow(px: number): boolean {
  return window.matchMedia(`(max-width: ${px - 0.02}px)`).matches;
}

/** What the tooltip layer shows: the element, its text, and the x to follow (pointer) or null (centre on it). */
export interface TipTarget {
  el: HTMLElement;
  text: string;
  x: number | null;
}

/** The element or a descendant is clipped (ellipsis, line-clamp). */
function isCut(el: Element): boolean {
  for (const e of [el, ...el.querySelectorAll("*")]) if (e.scrollWidth > e.clientWidth + 1 || e.scrollHeight > e.clientHeight + 1) return true;
  return false;
}

const tipOf = (t: EventTarget | null): HTMLElement | null => (t instanceof Element ? t.closest<HTMLElement>("[data-tip]") : null);

let hideActive: () => void = () => {};
/** Hide the tooltip now (an overlay opened, the screen changed). */
export function hideTips(): void {
  hideActive();
}

const LONG_PRESS_MS = 500;
const TOUCH_LINGER_MS = 1500;
const SLOP_PX = 10;

/**
 * Delegated tooltip tracking for every `[data-tip]` element — one set of
 * listeners for the whole page.
 * Mouse: shown after `delay`, follows the pointer, moving to a neighbour switches at once.
 * Keyboard: shown on :focus-visible.
 * Touch (or a `(hover: none)` device): no hover/focus tooltips at all; only a long
 * press shows one, and that press does not also click. It hides on lift + 1.5 s,
 * on scroll or a tap elsewhere.
 * Always hidden on route change, window blur, tab hide, `hideTips()`, and as soon
 * as its element leaves the DOM.
 */
export function watchTips(cb: (t: TipTarget | null) => void, delay = 100): () => void {
  const noHover = window.matchMedia("(hover: none)");
  let cur: HTMLElement | null = null;
  let shown = false;
  let timer = 0;
  let frame = 0;
  let press: { el: HTMLElement; id: number; x: number; y: number; fired: boolean } | null = null;
  let eatClickUntil = 0;
  const clear = () => window.clearTimeout(timer);
  const hide = () => {
    clear();
    cancelAnimationFrame(frame);
    if (cur || shown) cb(null);
    cur = null;
    shown = false;
  };
  hideActive = () => {
    press = null;
    hide();
  };
  // never outlive the anchor: re-render or navigation may remove it without any event
  const watchAnchor = () => {
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(() => {
      if (!shown || !cur) return;
      if (!cur.isConnected) return hide();
      watchAnchor();
    });
  };
  const show = (el: HTMLElement, x: number | null) => {
    const text = el.dataset.tip;
    if (!text || (el.hasAttribute("data-tip-cut") && !isCut(el))) return hide();
    cur = el;
    shown = true;
    cb({ el, text, x });
    watchAnchor();
  };
  const mouse = (e: PointerEvent) => e.pointerType !== "touch" && !noHover.matches;
  const over = (e: PointerEvent) => {
    if (!mouse(e)) return;
    const el = tipOf(e.target);
    if (el === cur) return;
    if (!el) return hide();
    clear();
    if (shown) return show(el, e.clientX); // gliding along pills: no second wait
    cur = el;
    const x = e.clientX;
    timer = window.setTimeout(() => show(el, x), delay);
  };
  const move = (e: PointerEvent) => {
    if (press && e.pointerId === press.id && !press.fired && Math.hypot(e.clientX - press.x, e.clientY - press.y) > SLOP_PX) {
      press = null;
      clear();
      return;
    }
    if (!mouse(e) || !cur) return;
    if (shown) cb({ el: cur, text: cur.dataset.tip ?? "", x: e.clientX });
  };
  const out = (e: PointerEvent) => {
    if (!mouse(e) || !cur) return;
    const to = e.relatedTarget as Node | null;
    if (!to || !cur.contains(to)) {
      if (!tipOf(to)) hide();
    }
  };
  const down = (e: PointerEvent) => {
    const el = tipOf(e.target);
    if (e.pointerType !== "touch") {
      if (!el) hide();
      return;
    }
    // touch: any new press hides what is shown; a press on a tip element arms the long press
    hide();
    press = el ? { el, id: e.pointerId, x: e.clientX, y: e.clientY, fired: false } : null;
    if (!el) return;
    timer = window.setTimeout(() => {
      if (!press || press.el !== el || !el.isConnected) return;
      press.fired = true;
      show(el, null);
    }, LONG_PRESS_MS);
  };
  const up = (e: PointerEvent) => {
    if (!press || e.pointerId !== press.id) return;
    const fired = press.fired;
    press = null;
    if (!fired) return clear();
    // the long press was the gesture: its click must not also open/toggle the item
    eatClickUntil = Date.now() + 800;
    clear();
    timer = window.setTimeout(hide, TOUCH_LINGER_MS);
  };
  const cancel = (e: PointerEvent) => {
    if (press && e.pointerId === press.id) {
      press = null;
      hide();
    }
  };
  const click = (e: MouseEvent) => {
    if (Date.now() > eatClickUntil) return;
    eatClickUntil = 0;
    e.preventDefault();
    e.stopPropagation();
  };
  // a long press also asks for the context menu / text callout
  const menu = (e: Event) => {
    if (press?.fired || Date.now() <= eatClickUntil) e.preventDefault();
  };
  const focusIn = (e: FocusEvent) => {
    if (noHover.matches) return;
    const el = tipOf(e.target);
    if (el && el === e.target && el.matches(":focus-visible")) {
      clear();
      show(el, null);
    }
  };
  const focusOut = (e: FocusEvent) => {
    if (cur && e.target === cur) hide();
  };
  const key = (e: KeyboardEvent) => {
    if (e.key === "Escape" && shown) hide();
  };
  const visibility = () => document.hidden && hideActive();
  const opts = { capture: true, passive: true } as const;
  window.addEventListener("pointerover", over, opts);
  window.addEventListener("pointermove", move, opts);
  window.addEventListener("pointerout", out, opts);
  window.addEventListener("pointerdown", down, opts);
  window.addEventListener("pointerup", up, opts);
  window.addEventListener("pointercancel", cancel, opts);
  window.addEventListener("click", click, true);
  window.addEventListener("contextmenu", menu, true);
  window.addEventListener("focusin", focusIn, true);
  window.addEventListener("focusout", focusOut, true);
  window.addEventListener("keydown", key, true);
  window.addEventListener("scroll", hideActive, opts);
  window.addEventListener("blur", hideActive);
  window.addEventListener("hashchange", hideActive);
  window.addEventListener("popstate", hideActive);
  document.addEventListener("visibilitychange", visibility);
  return () => {
    hide();
    hideActive = () => {};
    window.removeEventListener("pointerover", over, true);
    window.removeEventListener("pointermove", move, true);
    window.removeEventListener("pointerout", out, true);
    window.removeEventListener("pointerdown", down, true);
    window.removeEventListener("pointerup", up, true);
    window.removeEventListener("pointercancel", cancel, true);
    window.removeEventListener("click", click, true);
    window.removeEventListener("contextmenu", menu, true);
    window.removeEventListener("focusin", focusIn, true);
    window.removeEventListener("focusout", focusOut, true);
    window.removeEventListener("keydown", key, true);
    window.removeEventListener("scroll", hideActive, true);
    window.removeEventListener("blur", hideActive);
    window.removeEventListener("hashchange", hideActive);
    window.removeEventListener("popstate", hideActive);
    document.removeEventListener("visibilitychange", visibility);
  };
}

export function viewportWidth(): number {
  return window.innerWidth;
}

/** Where page-level floating layers (tooltip) mount. */
export function portalRoot(): HTMLElement {
  return document.body;
}

/** Some text is selected (a click that ends a selection drag is not a "click on empty space"). */
export function hasTextSelection(): boolean {
  return (window.getSelection()?.toString() ?? "") !== "";
}
