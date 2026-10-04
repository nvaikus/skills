# Field notes: measured behaviour and traps

Observed on Claude Code 2.1.x. Re-verify after a major upgrade.

## Hook runtime

- Windows runs hooks and the statusLine through Git Bash if installed, otherwise PowerShell. PowerShell reads the payload with `$in = $input | Out-String | ConvertFrom-Json`. Transcripts sit under `%USERPROFILE%\.claude\projects\` (or `CLAUDE_CONFIG_DIR`).
- Inside subagents and teammates, tool-event hooks receive `agent_id` and `agent_type`. When a subagent compacts, PreCompact and PostCompact name no agent whatsoever (payload keys: `custom_instructions cwd hook_event_name prompt_id session_id transcript_path trigger`), and SessionStart never fires for subagents. That is why Watch reads the agent's own log.
- The only source of the main session's size is the statusLine JSON; no hook payload includes it. `total_input_tokens` = input + cache read + cache creation.
- PostToolUse `additionalContext` reaches the model and lands in the transcript as a `"type":"attachment"` line: grep for the order text there to prove delivery in a live session.
- SessionStart `compact` fires for both automatic and `/compact`, main session only.
- Hook commands in settings.json are fixed when a session starts; script bodies are re-read on every call. Edit a script → effective at once; edit settings → next session. Hence the installer turns old script files into forwards instead of deleting them.
- The payload `cwd` tracks every `cd` the shell makes, which can make the suggested `<repo>` wrong; the 12 h list in Reorient covers that.

## Transcripts

- Main: `~/.claude/projects/<project-dir>/<session_id>.jsonl`. Subagents: `<session_id>/subagents/agent-<agent_id>.jsonl` and a sibling `.meta.json` holding `agentType`, `name`, `taskKind`, `spawnDepth`.
- In assistant lines the `"usage"` key comes ahead of `"type":"assistant"`: grep for each key separately, order-free.
- Each compaction writes one `"subtype":"compact_boundary"` line (its `compactMetadata` holds `preTokens` and `postTokens`), and the summary itself is a message flagged `"isCompactSummary":true`. The subagent size reading lags one message.

## Calibration

- `autoCompactWindow: 200000` compacted at 166–171k `preTokens`: the window minus a ~32k output reserve. 110k / 145k leaves ~23k headroom, enough for the one-message lag.
- Telling a subagent compaction apart from a main one inside PreCompact/PostCompact: the main session cannot compact below NUDGE, so a lower main counter means a subagent did; the newest subagent log names it. A heuristic, fine for calibration labels.
- Sample: out of 611 main sessions only one had ever compacted, yet during a single long session teammates hit compaction 4 times. Covering subagents is what pays off.
- Recalibrate from `~/.claude/.ctx-usage.d/compact-log.tsv`.

## Proving a port

Mirror `scripts/selftest.sh`:

1. settings.json references all four hooks.
2. Main session, override `1000 2000 500`: counter at 1500 gives the first order, an immediate repeat gives nothing, counter at 2500 gives the second.
3. Subagent: a fake log whose single assistant usage line sums to 1500 gives the first order pointing at the brief; one more line with a `compact_boundary` subtype gives the post-compaction order.
4. A PostCompact payload carrying `compact_summary` leaves a new file under `progress/compact/`.
5. A SessionStart payload with source `compact` prints the order and both lists.
6. A PreCompact payload adds a line to `compact-log.tsv`.

Remove every state file the check created.
