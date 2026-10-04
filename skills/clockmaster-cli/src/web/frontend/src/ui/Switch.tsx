export function Switch({ checked, onChange, label, disabled, size = "md" }: { checked: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean; size?: "sm" | "md" }) {
  const sm = size === "sm";
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={(e) => {
        e.stopPropagation();
        onChange(!checked);
      }}
      className={`relative inline-flex shrink-0 items-center rounded-full transition-colors disabled:opacity-45 ${
        sm ? "h-5 w-8" : "h-6 w-10"
      } ${checked ? "bg-ok" : "bg-idle/60"}`}
    >
      <span
        className={`absolute rounded-full bg-white shadow-sm transition-transform ${sm ? "size-4 left-0.5" : "size-5 left-0.5"} ${
          checked ? (sm ? "translate-x-3" : "translate-x-4") : "translate-x-0"
        }`}
      />
    </button>
  );
}
