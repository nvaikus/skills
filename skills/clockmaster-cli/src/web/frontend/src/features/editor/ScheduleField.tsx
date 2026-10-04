import { useSchedulePreview, useNow } from "../../data/hooks";
import { sentence, when } from "../../lib/format";
import { TextField } from "../../ui/Field";
import { Icon } from "../../ui/Icon";

const PRESETS = [
  { label: "every 15 min", cron: "*/15 * * * *" },
  { label: "hourly", cron: "0 * * * *" },
  { label: "daily 9:00", cron: "0 9 * * *" },
  { label: "weekdays 9:00", cron: "0 9 * * 1-5" },
];

const lower = (s: string) => s.replace(/^(Today|Tomorrow|Yesterday)/, (w) => w.toLowerCase());

/** Cron is the input; right under it the server's plain-words reading + next run (GET /api/schedule). */
export function ScheduleField({ value, onChange, problem, autoFocus }: { value: string; onChange: (v: string) => void; problem?: string; autoFocus?: boolean }) {
  const cron = value.trim().replace(/\s+/g, " ");
  const { data, error, stale } = useSchedulePreview(problem || !cron ? null : cron);
  const now = useNow(30000);
  const err = problem ?? (stale ? undefined : (error ?? undefined));
  const next = data?.next[0];
  return (
    <div className="flex flex-col gap-1.5">
      <TextField label="Schedule (cron)" mono value={value} onChange={onChange} placeholder="*/30 * * * *" error={err} autoFocus={autoFocus} />
      {!err && data && (
        <p aria-live="polite" className={`flex flex-wrap items-center gap-x-1.5 text-caption transition ${stale ? "opacity-60" : ""}`}>
          <Icon name="clock" size={13} className="shrink-0 text-fg-3" />
          <span className="text-fg-1">{sentence(data.text)}</span>
          <span className="whitespace-nowrap text-fg-3">
            · next: {next ? lower(when(next, now)) : "never (no such date)"}
          </span>
        </p>
      )}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-caption text-fg-3">
        <span>Fields: minute hour day month weekday ·</span>
        {PRESETS.map((p) => (
          <button key={p.cron} type="button" onClick={() => onChange(p.cron)} className="text-accent hover:underline">
            {p.label}
          </button>
        ))}
      </div>
    </div>
  );
}
