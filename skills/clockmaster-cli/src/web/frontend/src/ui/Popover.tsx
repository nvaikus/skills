import { useEffect, useRef, useState, type ReactNode } from "react";
import { onPointerDownAnywhere } from "../platform/web/dom";
import { Icon, type IconName } from "./Icon";
import { useLayer } from "./overlay";

/** Anchored panel: `trigger` gets {open, toggle}; closes on Escape (if top) and outside press. */
export function Popover({ trigger, children, align = "end", width = "w-56" }: { trigger: (p: { open: boolean; toggle: () => void }) => ReactNode; children: (close: () => void) => ReactNode; align?: "start" | "end"; width?: string }) {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  const close = () => setOpen(false);
  useLayer(open, close);
  useEffect(() => {
    if (!open) return;
    return onPointerDownAnywhere((t) => {
      if (wrap.current && t && !wrap.current.contains(t)) setOpen(false);
    });
  }, [open]);
  return (
    <div ref={wrap} className="relative inline-flex">
      {trigger({ open, toggle: () => setOpen((o) => !o) })}
      {open && (
        <div
          role="menu"
          className={`absolute top-full z-(--z-popover) mt-1.5 ${width} animate-rise rounded-xl border border-line bg-surface p-1 shadow-xl ${align === "end" ? "right-0" : "left-0"}`}
        >
          {children(close)}
        </div>
      )}
    </div>
  );
}

export function MenuItem({ icon, children, onSelect, danger, checked, hint }: { icon?: IconName; children: ReactNode; onSelect: () => void; danger?: boolean; checked?: boolean; hint?: ReactNode }) {
  return (
    <button
      type="button"
      role={checked === undefined ? "menuitem" : "menuitemradio"}
      aria-checked={checked}
      onClick={onSelect}
      className={`flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left text-body transition hover:bg-raised ${danger ? "text-fail" : "text-fg-1"}`}
    >
      {icon && <Icon name={icon} size={15} className={danger ? "" : "text-fg-3"} />}
      <span className="min-w-0 flex-1">
        <span className="block truncate">{children}</span>
        {hint && <span className="block truncate text-caption text-fg-3">{hint}</span>}
      </span>
      {checked && <Icon name="check" size={14} className="text-accent" />}
    </button>
  );
}

export function MenuDivider() {
  return <div role="separator" className="my-1 h-px bg-line-soft" />;
}
