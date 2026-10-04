// The one shape for async states.
import type { ReactNode } from "react";
import { Icon, type IconName } from "./Icon";
import { Spinner } from "./Button";

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center justify-center gap-2 py-10 text-caption text-fg-3">
      <Spinner /> {label}
    </div>
  );
}

export function ErrorText({ children, inline }: { children: ReactNode; inline?: boolean }) {
  return (
    <div role="alert" className={`flex items-start gap-2 text-caption text-fail ${inline ? "" : "rounded-lg bg-fail/8 px-3 py-2"}`}>
      <Icon name="alert" size={14} className="mt-px" />
      <span className="min-w-0 break-words whitespace-pre-wrap">{children}</span>
    </div>
  );
}

export function EmptyState({ icon = "clock", title, children, compact }: { icon?: IconName; title: string; children?: ReactNode; compact?: boolean }) {
  return (
    <div className={`flex flex-col items-center justify-center text-center ${compact ? "gap-1.5 px-3 py-5" : "gap-2 px-6 py-12"}`}>
      <div className={`grid place-items-center rounded-full bg-raised text-fg-3 ${compact ? "size-8" : "size-10"}`}>
        <Icon name={icon} size={compact ? 16 : 18} />
      </div>
      <div className="text-body font-medium text-fg-1">{title}</div>
      {children && <div className="max-w-sm text-caption text-fg-3">{children}</div>}
    </div>
  );
}

export function Notice({ children, tone = "info" }: { children: ReactNode; tone?: "info" | "warn" }) {
  return (
    <div className={`flex items-start gap-2 rounded-xl px-3 py-2 text-caption ${tone === "warn" ? "bg-warn/10 text-fg-1" : "bg-raised text-fg-2"}`}>
      <Icon name={tone === "warn" ? "alert" : "info"} size={14} className={`mt-px ${tone === "warn" ? "text-warn" : "text-fg-3"}`} />
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}
