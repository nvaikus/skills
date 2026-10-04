import { useEffect, useId, useRef, type ReactNode } from "react";
import { activeElement, focusFirst, trapTab } from "../platform/web/dom";
import { IconButton } from "./Button";
import { useLayer } from "./overlay";

/**
 * Centered dialog on desktop, bottom sheet on phones — same component.
 * A scrim click does NOT close it (forms would lose input); Escape and the
 * close button do.
 */
export function Dialog({ open, onClose, title, subtitle, children, footer, width = "md" }: { open: boolean; onClose: () => void; title: ReactNode; subtitle?: ReactNode; children: ReactNode; footer?: ReactNode; width?: "sm" | "md" | "lg" }) {
  useLayer(open, onClose);
  const box = useRef<HTMLDivElement>(null);
  const titleId = useId();
  useEffect(() => {
    if (!open) return;
    const back = activeElement();
    focusFirst(box.current);
    return () => back?.focus?.();
  }, [open]);
  if (!open) return null;
  const w = width === "sm" ? "sm:max-w-sm" : width === "lg" ? "sm:max-w-2xl" : "sm:max-w-lg";
  return (
    <div className="fixed inset-0 z-(--z-dialog) flex items-end justify-center bg-scrim sm:items-center sm:p-6">
      <div
        ref={box}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onKeyDown={(e) => box.current && trapTab(e.nativeEvent, box.current)}
        className={`flex max-h-[92dvh] w-full ${w} animate-rise flex-col rounded-t-2xl border border-line bg-surface shadow-2xl sm:rounded-2xl pb-[env(safe-area-inset-bottom)]`}
      >
        <header className="flex items-start gap-3 px-5 pt-4 pb-3">
          <div className="min-w-0 flex-1">
            <h2 id={titleId} className="text-title font-semibold text-fg-1">
              {title}
            </h2>
            {subtitle && <div className="mt-0.5 text-caption text-fg-3">{subtitle}</div>}
          </div>
          <IconButton icon="x" label="Close" size="sm" onClick={onClose} />
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 pb-4">{children}</div>
        {footer && <footer className="flex flex-wrap items-center justify-end gap-2 border-t border-line-soft px-5 py-3">{footer}</footer>}
      </div>
    </div>
  );
}
