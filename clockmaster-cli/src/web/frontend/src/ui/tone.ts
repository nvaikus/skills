// Tone → class bundles. Literal strings so Tailwind sees them.
import type { Tone } from "../lib/status";

export const toneText: Record<Tone, string> = {
  ok: "text-ok",
  fail: "text-fail",
  warn: "text-warn",
  live: "text-live",
  queue: "text-queue",
  idle: "text-fg-3",
};
export const toneBg: Record<Tone, string> = {
  ok: "bg-ok",
  fail: "bg-fail",
  warn: "bg-warn",
  live: "bg-live",
  queue: "bg-queue",
  idle: "bg-idle",
};
export const toneSoft: Record<Tone, string> = {
  ok: "bg-ok/12 text-ok",
  fail: "bg-fail/12 text-fail",
  warn: "bg-warn/14 text-warn",
  live: "bg-live/12 text-live",
  queue: "bg-queue/12 text-queue",
  idle: "bg-raised text-fg-2",
};
