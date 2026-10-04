import type { ReactNode } from "react";

export interface SegOption<T extends string> {
  value: T;
  label: ReactNode;
}

export function Segmented<T extends string>({ options, value, onChange, label, size = "md" }: { options: readonly SegOption<T>[]; value: T | null; onChange: (v: T) => void; label: string; size?: "sm" | "md" }) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex shrink-0 items-center rounded-lg bg-raised p-0.5">
      {options.map((o) => {
        const on = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={on}
            onClick={() => onChange(o.value)}
            className={`inline-flex items-center justify-center gap-1 rounded-md sm:gap-1.5 font-medium transition whitespace-nowrap ${
              size === "sm" ? "h-6 px-1.5 text-caption sm:px-2" : "h-8 px-3 text-caption"
            } ${on ? "bg-surface text-fg-1 shadow-sm" : "text-fg-2 hover:text-fg-1"}`}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
