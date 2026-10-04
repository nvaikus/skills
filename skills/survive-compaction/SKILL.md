---
name: survive-compaction
description: Keeps long Claude Code work recoverable across auto-compaction. Deterministic hooks measure context size and order the model to write a progress doc before compaction (main session and every subagent/teammate), order it to re-read and update that doc right after compaction, and archive each compaction summary. Ships a shell-independent contract and a bash + jq implementation that comes with tests, an installer, a self-test and an uninstaller. Use when installing these hooks on a machine, porting them to PowerShell or another runtime, tuning the token limits, migrating from compact-guard, or debugging why a progress-doc order did or did not appear. Triggers - context got compacted and work was lost, survive compaction, progress doc hooks, context size reminder, auto-compact threshold, PreCompact / PostCompact hook, statusline context counter, checkpoint.
---

# survive-compaction

Compaction swaps the exact history for a summary. A CLAUDE.md rule "keep a progress doc" alone does not work: the model cannot see how full its context is. These hooks can, and they turn the rule into timed orders. No model calls; the model is the only writer of progress docs.

## Invariants

- Hooks measure and instruct; they never write `~/.claude/progress/<repo>-<task-slug>.md`.
- Limits are absolute token counts derived from `autoCompactWindow`, never `used_percentage`.
- The main session's size exists only in the statusLine JSON, so the statusLine must store it (`meter.sh`, or an existing statusline that already writes `~/.claude/.ctx-usage.d/<session>`).
- Subagents get no compaction events and no SessionStart: everything about them comes from their own transcript.

## Routing

| Situation | Do |
|---|---|
| Install / update / migrate from compact-guard, host has bash + jq (Linux, macOS, or Git Bash on Windows) | `bash scripts/install.sh`, then `bash scripts/selftest.sh`. Re-runnable. |
| No bash + jq (e.g. PowerShell only) | Implement `references/spec.md`; read `references/field-notes.md` first and prove it with its checklist |
| Tune limits | edit `~/.claude/hooks/checkpoint/checkpoint.conf` (`NUDGE_AT FINAL_AT REARM_BELOW` in tokens, `COMPACT_NEAR_K` in k); calibration data in `field-notes.md` |
| Order missing, wrong label, odd behaviour | `references/field-notes.md`, then `references/spec.md` |
| Remove | `bash scripts/uninstall.sh` (keeps progress docs and the CLAUDE.md section) |
| Change a script | edit `scripts/`, keep `python3 -m unittest discover -s dev/tests` green, re-run `install.sh` |

Any install or settings change applies to sessions started afterwards.

## Memory

`~/.claude/checkpoint/memory.md`: local lessons, outside the skill (updates keep it). Read first; create on first write. Cost a question, retry or context → one imperative line now; why only if it prevents a mistake. Situational → `memory/<topic>.md` behind a `<trigger> → file` line. Every-user fact → skill defect (unsure → note; proven → move it in).

## Fix on friction

Gap, confusing/flooding/noisy output, stale text = skill defect; no silent workarounds. Small → fix now. Large → background `opus` teammate, one-message ticket (fact, proving command, output) fixing the faulty layer: SKILL.md, references/, scripts/, tool. Continue only if unblocked. Tracked (`skilltap status`) → edit its clone, pull, push; else in place.

> Source: https://github.com/nvaikus/skills/blob/main/skills/survive-compaction/SKILL.md
> Install via skilltap for auto-updates: https://github.com/nvaikus/skills/blob/main/skills/skilltap/SKILL.md
