# Hook contract (shell-independent)

What any implementation must do. `scripts/` is the bash + jq one; port this to PowerShell, python or anything else the host runs hooks with.

## Parts

| Part | Claude Code entry | Does | Model sees |
|---|---|---|---|
| Meter | `statusLine` command (wraps the previous one) | on every render, write `context_window.total_input_tokens` to `<state>/<session>` | nothing extra |
| Watch | `PostToolUse`, no matcher | context-size orders; subagent post-compaction order | JSON `additionalContext` |
| Reorient | `SessionStart`, matcher `compact` | post-compaction order for the main session | plain stdout |
| Ledger | `PreCompact` | append a calibration row; exit 0 whatever happens | nothing |
| Archive | `PostCompact` | save `compact_summary` to the progress archive | nothing |
| Rule | `~/.claude/CLAUDE.md` | append `templates/claude-md-rule.md` when no `# Progress doc` heading exists | the rule the orders cite |

Hooks only measure and instruct. The model alone writes the progress doc: `<repo>-<task-slug>.md` inside `~/.claude/progress/`, where `<repo>` is the basename of `cwd`.

## Watch

- No `session_id` → do nothing.
- Main session: size = `<state>/<session>`; file absent → do nothing.
- Subagent (payload has `agent_id`): own state key `<session>__<agent>`. Its log is `${transcript_path%.jsonl}/subagents/agent-<agent_id>.jsonl`, else `<agent_id>.jsonl`, else the newest `agent-*<id>*.jsonl`; none → do nothing. Size = the last line among the final 150 that has both `"usage"` and `"type":"assistant"` (either order): `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`.
- Two orders per arming cycle, each at most once:
  - size ≥ FINAL and not yet given → "compaction is close, save the final state now, anything not in the doc may be lost". Giving it also counts as giving the first.
  - else size ≥ NUDGE and not yet given → "the CLAUDE.md rule is in force; write or refresh the doc (goal, decisions, finished vs open, next action, file paths) before the next step".
  - size < REARM → both armed again.
- Order target: main → `~/.claude/progress/<repo>-<task-slug>.md` plus up to 3 existing `<repo>-*.md`, newest first, "refresh one of these instead". Subagent → "the path your brief gave you", with the default path as fallback, no list.
- Subagent compaction: count `"subtype":"compact_boundary"` lines in its log. A higher count than at the previous call (not the first look) → Reorient's subagent text, once, and re-arm. A `.pending` marker left by Archive does the same on the next call.

## Reorient

Main text: compaction just happened, the CLAUDE.md rule applies before any other step. Subagent text: compaction happened inside agent `<agent_type or agent_id>`, only the summary survived, a doc path from the brief wins. Both continue with:

1. up to 5 `<repo>-*.md` docs, newest first, each with its HH:MM modification time;
2. up to 5 docs modified in the last 12 h (catches a `<repo>` that drifted with `cd`);
3. "none" for an empty list;
4. three steps: a listed doc is this task's → read it, update it from the summary; none is → start `<repo>-<task-slug>.md` immediately, as the summary still has the detail; raw summaries live in `progress/compact/<session8>*-NN.md`, reference only.

## Ledger and Archive

- Ledger row (`<state>/compact-log.tsv`, header written once): `when session8 agent trigger tokens_at_compact cwd input_keys`. Agent = `type(id)` or `main`. Main whose counter is below NUDGE → it was a subagent: `teammate?:<newest subagent log name>`, tokens `n/a(main counter=N)`. Named agent → tokens `n/a(subagent)`.
- Archive: no session or no summary → nothing. File `progress/compact/<session8>[-<label>]-NN.md`, NN = highest existing + 1. Label = sanitized agent type/id (24 chars), else `teammate-<newest subagent>` (30 chars) when the main counter is below NUDGE. Header lists time, trigger, agent, cwd, full session id. Prune archive files older than 14 days. Payload carries `agent_id` → leave `<state>/<session>__<agent>.pending`.

## State and limits

- `<state>` = `~/.claude/.ctx-usage.d/` (statuslines that already write the counter there need no wrapper). Keys: ids with every char outside `[A-Za-z0-9-]` turned into `_`. Files: `<key>` counter, `<key>.lvl` orders given, `<key>.seen` boundary count, `<key>.pending`, `<session>.override`, `compact-log.tsv`. Meter prunes everything but `.tsv` older than 7 days when a new session's counter is first written.
- Limits are absolute tokens, derived from `autoCompactWindow` (default 200000): NUDGE 55 %, FINAL 72.5 %, REARM 30 %, expected compaction 84 % (shown in the text, in k). Never `used_percentage`: it measures against the whole window instead of the point where compaction fires.
- Override for tests: `<state>/<session>.override` = `NUDGE FINAL [REARM]`.
