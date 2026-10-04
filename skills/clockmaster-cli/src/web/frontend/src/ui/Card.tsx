import type { ReactNode } from "react";

/** `fill`: stretch to the parent's remaining height (a flex column), children laid out as a column. */
export function Card({ children, pad = true, as: As = "section", label, fill }: { children: ReactNode; pad?: boolean; as?: "section" | "div"; label?: string; fill?: boolean }) {
  return (
    <As aria-label={label} className={`bg-surface border border-line rounded-2xl ${pad ? "p-4 sm:p-5" : "overflow-hidden"} ${fill ? "flex min-h-0 flex-1 flex-col" : ""}`}>
      {children}
    </As>
  );
}

/** Small uppercase heading row with an optional right slot. */
export function SectionHead({ title, right, id }: { title: ReactNode; right?: ReactNode; id?: string }) {
  return (
    <div className="flex items-center justify-between gap-3 min-h-9">
      <h2 id={id} className="text-caption font-semibold uppercase tracking-wider text-fg-3">
        {title}
      </h2>
      {right && <div className="flex items-center gap-2 min-w-0">{right}</div>}
    </div>
  );
}
