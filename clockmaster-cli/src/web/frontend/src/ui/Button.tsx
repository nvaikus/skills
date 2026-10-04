import type { ButtonHTMLAttributes, ReactNode, Ref } from "react";
import { Icon, type IconName } from "./Icon";
import { tip } from "./Tooltip";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md";

const V: Record<Variant, string> = {
  primary: "bg-accent text-on-accent hover:bg-accent/90",
  secondary: "bg-surface text-fg-1 border border-line hover:bg-raised",
  ghost: "text-fg-2 hover:bg-raised hover:text-fg-1",
  danger: "bg-fail text-white hover:bg-fail/90",
};
const S: Record<Size, string> = {
  sm: "h-7 px-2.5 gap-1.5 text-caption rounded-md",
  md: "h-9 px-3.5 gap-2 text-body rounded-lg",
};
const BASE =
  "inline-flex items-center justify-center font-medium whitespace-nowrap select-none transition active:scale-[0.97] disabled:opacity-45 disabled:pointer-events-none";

interface Props extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "className" | "title"> {
  variant?: Variant;
  size?: Size;
  icon?: IconName;
  busy?: boolean;
  children?: ReactNode;
  wide?: boolean;
  ref?: Ref<HTMLButtonElement>;
}

/** A labelled button: no tooltip (its text says what it does). */
export function Button({ variant = "secondary", size = "md", icon, busy, children, wide, disabled, ...rest }: Props) {
  return (
    <button type="button" {...rest} disabled={disabled || busy} className={`${BASE} ${V[variant]} ${S[size]} ${wide ? "w-full" : ""}`}>
      {busy ? <Spinner /> : icon ? <Icon name={icon} size={size === "sm" ? 14 : 16} /> : null}
      {children}
    </button>
  );
}

interface IconButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "className" | "children"> {
  icon: IconName;
  label: string;
  size?: Size;
  active?: boolean;
  ref?: Ref<HTMLButtonElement>;
}

export function IconButton({ icon, label, size = "md", active, title, ...rest }: IconButtonProps) {
  return (
    <button
      type="button"
      aria-label={label}
      {...rest}
      {...tip(title ?? label)}
      className={`${BASE} ${size === "sm" ? "size-7 rounded-md" : "size-9 rounded-lg"} ${
        active ? "bg-raised text-fg-1" : "text-fg-2 hover:bg-raised hover:text-fg-1"
      }`}
    >
      <Icon name={icon} size={size === "sm" ? 14 : 16} />
    </button>
  );
}

export function Spinner({ size = 14 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" className="animate-spin shrink-0" aria-hidden="true">
      <circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" strokeOpacity="0.25" strokeWidth="2" />
      <path d="M14 8a6 6 0 0 0-6-6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}
