// The one icon set: 16px-grid strokes, currentColor. Features pass a name.
const P: Record<string, string> = {
  play: "M5 3.5v9l7-4.5z",
  stop: "M4.5 4.5h7v7h-7z",
  "chevron-right": "M6 3.5 10.5 8 6 12.5",
  "chevron-down": "M3.5 6 8 10.5 12.5 6",
  "chevron-left": "M10 3.5 5.5 8l4.5 4.5",
  search: "M7 12A5 5 0 1 0 7 2a5 5 0 0 0 0 10zm3.6-1.4L14 14",
  sun: "M8 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM8 1v1.5M8 13.5V15M1 8h1.5M13.5 8H15M3 3l1 1M12 12l1 1M3 13l1-1M12 4l1-1",
  moon: "M13.5 9.5A5.5 5.5 0 0 1 6.5 2.5a5.5 5.5 0 1 0 7 7z",
  monitor: "M2 3h12v8H2zM6 14h4M8 11v3",
  more: "M3.5 8h.01M8 8h.01M12.5 8h.01",
  edit: "M10.5 2.5l3 3L6 13H3v-3zM9 4l3 3",
  trash: "M2.5 4h11M6 4V2.5h4V4M4 4l.7 9.5h6.6L12 4M6.5 6.5v5M9.5 6.5v5",
  bell: "M4 11V7a4 4 0 0 1 8 0v4l1 1.5H3zM6.5 14a1.5 1.5 0 0 0 3 0",
  sound: "M2.5 6h2.5L8.5 3v10L5 10H2.5zM11 5.5a3.5 3.5 0 0 1 0 5M12.8 3.5a6 6 0 0 1 0 9",
  copy: "M5.5 5.5h8v8h-8zM10.5 5.5v-3h-8v8h3",
  terminal: "M2 3h12v10H2zM4.5 6l2 2-2 2M8 10h3.5",
  refresh: "M13.5 8A5.5 5.5 0 1 1 11.8 4M13.5 2.5V5H11",
  alert: "M8 2 14.5 13.5h-13zM8 6.5v3M8 11.5h.01",
  check: "M3 8.5 6.5 12 13 4.5",
  x: "M4 4l8 8M12 4l-8 8",
  clock: "M8 14.5a6.5 6.5 0 1 0 0-13 6.5 6.5 0 0 0 0 13zM8 4.5V8l2.5 1.5",
  info: "M8 14.5a6.5 6.5 0 1 0 0-13 6.5 6.5 0 0 0 0 13zM8 7.5v4M8 5h.01",
  history: "M2.5 8a5.5 5.5 0 1 0 1.6-3.9M2.5 2.5v2.5H5M8 5v3l2 1.5",
  timeline: "M2 4h7M5 8h9M3 12h6",
  sync: "M2.5 7a5.5 5.5 0 0 1 10-2.5M13.5 2.5v2.5H11M13.5 9a5.5 5.5 0 0 1-10 2.5M2.5 13.5V11H5",
  folder: "M2 4.5V12.5h12V5.5H7.5L6 4z",
  spark: "M8 1.5v4M8 10.5v4M1.5 8h4M10.5 8h4M3.5 3.5l2.5 2.5M10 10l2.5 2.5M3.5 12.5 6 10M10 6l2.5-2.5",
  arrow: "M3 8h10M9 4l4 4-4 4",
  plus: "M8 3v10M3 8h10",
  minus: "M3 8h10",
  timer: "M8 14.5a5.5 5.5 0 1 0 0-11 5.5 5.5 0 0 0 0 11zM8 6v3M6.5 1.5h3M12.5 4l1-1",
};

export type IconName = keyof typeof P;

export function Icon({ name, size = 16, className = "" }: { name: IconName; size?: number; className?: string }) {
  const filled = name === "play" || name === "stop";
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      aria-hidden="true"
      className={`shrink-0 ${className}`}
      fill={filled ? "currentColor" : "none"}
      stroke="currentColor"
      strokeWidth={name === "more" ? 2.6 : 1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d={P[name]} />
    </svg>
  );
}
