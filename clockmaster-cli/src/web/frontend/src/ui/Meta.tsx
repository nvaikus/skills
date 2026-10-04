import type { ReactNode, Ref } from "react";
import { Icon, type IconName } from "./Icon";
import { tip, tipIfCut } from "./Tooltip";

/**
 * One fact in an inline meta row: icon, muted label, value. No pill: plain text
 * that only shows a soft hover when it is clickable. Truncates only with `max`.
 * `hint` = a tooltip for a setting whose label does not say it all; `full` = the
 * whole value, shown only while it is cut.
 */
export function Meta({ icon, label, children, hint, full, onClick, tone, max, ref, expanded }: { icon: IconName; label?: string; children: ReactNode; hint?: string; full?: string; onClick?: () => void; tone?: "warn"; max?: string; ref?: Ref<HTMLButtonElement>; expanded?: boolean }) {
  const cls = `-mx-1 inline-flex min-w-0 shrink-0 ${max ?? ""} items-center gap-1.5 rounded-md px-1 py-0.5 text-caption ${tone === "warn" ? "text-warn" : "text-fg-1"}`;
  const t = hint ? tip(hint) : tipIfCut(full);
  const body = (
    <>
      <Icon name={icon} size={13} className={`shrink-0 ${tone === "warn" ? "" : "text-fg-3"}`} />
      {label && <span className={`shrink-0 ${tone === "warn" ? "" : "text-fg-3"}`}>{label}</span>}
      <span className={max ? "min-w-0 truncate" : "whitespace-nowrap"}>{children}</span>
    </>
  );
  if (!onClick)
    return (
      <span {...t} className={cls}>
        {body}
      </span>
    );
  return (
    <button ref={ref} type="button" {...t} aria-expanded={expanded} onClick={onClick} className={`${cls} transition-colors hover:bg-raised`}>
      {body}
    </button>
  );
}
