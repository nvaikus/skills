import type { Run } from "./types";

const q = (s: string) => (/^[\w@%+=:,./~-]+$/.test(s) ? s : `'${s.replace(/'/g, `'\\''`)}'`);

/** Shell line that resumes the run's Claude session (display/copy fallback). */
export function resumeCommand(run: Run): string | null {
  if (!run.sessionId) return null;
  const cd = run.workdir ? `cd ${q(run.workdir)} && ` : "";
  return `${cd}claude --resume ${run.sessionId}`;
}

export const looksLikeClaude = (command: string) => /(^|[\s/;&|(])claude(\s|$)/.test(command);
