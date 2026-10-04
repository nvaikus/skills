import { useId, type ReactNode, type Ref } from "react";

// Below sm every field is 16px: iOS Safari zooms into a smaller focused field and never zooms back.
const INPUT =
  "w-full rounded-lg border bg-sunken px-3 py-2 text-fg-1 placeholder:text-fg-3 transition outline-none focus:border-accent focus:ring-2 focus:ring-accent/20";

export function TextField({ label, value, onChange, hint, error, mono, placeholder, autoFocus, multiline }: { label: string; value: string; onChange: (v: string) => void; hint?: ReactNode; error?: string; mono?: boolean; placeholder?: string; autoFocus?: boolean; multiline?: boolean }) {
  const id = useId();
  const cls = `${INPUT} ${error ? "border-fail" : "border-line"} ${mono ? "font-mono text-base sm:text-caption" : "text-base sm:text-body"}`;
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-caption font-medium text-fg-2">
        {label}
      </label>
      {multiline ? (
        <textarea id={id} rows={2} className={`${cls} resize-y`} value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} spellCheck={false} data-autofocus={autoFocus || undefined} aria-invalid={!!error} />
      ) : (
        <input id={id} className={cls} value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} spellCheck={false} autoComplete="off" data-autofocus={autoFocus || undefined} aria-invalid={!!error} />
      )}
      {error ? <span className="text-caption text-fail">{error}</span> : hint ? <span className="text-caption text-fg-3">{hint}</span> : null}
    </div>
  );
}

export function SearchField({ value, onChange, placeholder, label, size = "md", onBlur, ref }: { value: string; onChange: (v: string) => void; placeholder: string; label: string; size?: "sm" | "md"; onBlur?: () => void; ref?: Ref<HTMLInputElement> }) {
  return (
    <input
      type="search"
      aria-label={label}
      value={value}
      placeholder={placeholder}
      onChange={(e) => onChange(e.target.value)}
      ref={ref}
      onBlur={onBlur}
      className={`${INPUT} ${size === "sm" ? "h-7 px-2.5" : "h-8"} border-line py-1 text-base sm:text-caption`}
    />
  );
}

export function Checkbox({ checked, onChange, children }: { checked: boolean; onChange: (v: boolean) => void; children: ReactNode }) {
  return (
    <label className="flex cursor-pointer items-start gap-2.5 text-body text-fg-1">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="mt-0.5 size-4 accent-(--color-fail)" />
      <span>{children}</span>
    </label>
  );
}
