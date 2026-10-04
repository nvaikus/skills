// One overlay system: a stack; only the TOP layer gets Escape (captured on window,
// so it wins over inputs); dialogs trap focus and return it on close.
import { createContext, useContext, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { hideTips, onEscape, onPointerDownAnywhere } from "../platform/web/dom";

interface Layer {
  id: string;
  close: () => void;
}

const Ctx = createContext<{ push: (l: Layer) => void; pop: (id: string) => void; top: () => string | null; downOnLayer: () => boolean } | null>(null);

export function OverlayProvider({ children }: { children: ReactNode }) {
  const stack = useRef<Layer[]>([]);
  // was an overlay open when the current press started? (popovers close on that pointerdown, before the click)
  const down = useRef(false);
  useEffect(() => onPointerDownAnywhere(() => void (down.current = stack.current.length > 0)), []);
  const [api] = useState(() => ({
    downOnLayer: () => down.current || stack.current.length > 0,
    push: (l: Layer) => {
      hideTips(); // a tooltip never sits over a fresh dialog/popover
      stack.current.push(l);
    },
    pop: (id: string) => void (stack.current = stack.current.filter((l) => l.id !== id)),
    top: () => stack.current[stack.current.length - 1]?.id ?? null,
  }));
  useEffect(
    () =>
      onEscape((e) => {
        const top = stack.current[stack.current.length - 1];
        if (!top) return;
        e.preventDefault();
        e.stopPropagation();
        top.close();
      }),
    [],
  );
  return <Ctx.Provider value={api}>{children}</Ctx.Provider>;
}

/** Register an open overlay; Escape calls `onClose` only while it is on top. */
export function useLayer(open: boolean, onClose: () => void) {
  const ctx = useContext(Ctx);
  const id = useId();
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    if (!open || !ctx) return;
    ctx.push({ id, close: () => close.current() });
    return () => ctx.pop(id);
  }, [open, ctx, id]);
}

/** True when the click being handled was consumed by an overlay (one was open at its pointerdown, or still is). */
export function useOverlayGuard(): () => boolean {
  const ctx = useContext(Ctx);
  return () => ctx?.downOnLayer() ?? false;
}
