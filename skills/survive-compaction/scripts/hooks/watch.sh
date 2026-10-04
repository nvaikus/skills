#!/bin/bash
# watch.sh: PostToolUse hook, every tool.
# Main session: reads the statusline counter, issues the two context-size orders.
# Subagent (payload has agent_id): reads its own transcript for size and for new
# compact_boundary records, and hands it the post-compaction order (it gets no
# SessionStart of its own).
. "$(dirname "$0")/common.sh"
payload=$(cat)
IFS=$'\x1f' read -r sid aid tp cwd <<EOF
$(fields session_id agent_id transcript_path cwd)
EOF
[ -n "$sid" ] || exit 0
mkdir -p "$state_dir"
key=$(safe "$sid")

# Test aid: <state>/<session>.override = "NUDGE FINAL [REARM]".
if [ -f "$state_dir/$key.override" ]; then
  o1=""; o2=""; o3=""; read -r o1 o2 o3 < "$state_dir/$key.override" || true
  is_num "$o1" && NUDGE_AT=$o1; is_num "$o2" && FINAL_AT=$o2; is_num "$o3" && REARM_BELOW=$o3
fi

say() { jq -cn --arg t "$1" '{hookSpecificOutput:{hookEventName:"PostToolUse",additionalContext:$t}}'; }

if [ -n "$aid" ]; then
  key="${key}__$(safe "$aid")"
  reorient() { : > "$state_dir/$key.lvl"; say "$(printf '%s' "$payload" | "$here/reorient.sh")"; exit 0; }
  # archive.sh leaves this when PostCompact names the agent.
  if [ -f "$state_dir/$key.pending" ]; then rm -f "$state_dir/$key.pending"; reorient; fi

  subs="${tp%.jsonl}/subagents"; log=""
  for c in "$subs/agent-$aid.jsonl" "$subs/$aid.jsonl"; do [ -f "$c" ] && { log=$c; break; }; done
  [ -n "$log" ] || log=$(ls -t "$subs"/agent-*"${aid#agent-}"*.jsonl 2>/dev/null | sed -n 1p)
  [ -n "$log" ] || exit 0

  # Compact hooks carry no agent identity: a new boundary record in the
  # agent's own log is the only reliable signal that it was compacted.
  seen_now=$(grep -c '"subtype":"compact_boundary"' "$log" 2>/dev/null); is_num "$seen_now" || seen_now=0
  seen_before=""; [ -f "$state_dir/$key.seen" ] && seen_before=$(head -1 "$state_dir/$key.seen")
  printf '%s\n' "$seen_now" > "$state_dir/$key.seen"
  if is_num "$seen_before" && [ "$seen_now" -gt "$seen_before" ]; then reorient; fi

  used=$(tail -n 150 "$log" | grep -F '"usage"' | grep -F '"type":"assistant"' | tail -n 1 |
    jq -r '[.message.usage | .input_tokens, .cache_read_input_tokens, .cache_creation_input_tokens] | map(. // 0) | add' 2>/dev/null)
  doc="the progress doc whose path your brief gave you (no path given: ~/.claude/progress/<repo>-<task-slug>.md)"
  repo=""
else
  [ -f "$state_dir/$key" ] || exit 0
  used=$(head -1 "$state_dir/$key")
  repo=$(basename "${cwd:-$PWD}")
  doc="~/.claude/progress/${repo}-<task-slug>.md"
fi
is_num "$used" || exit 0

lvl_file="$state_dir/$key.lvl"
done_lv=""; [ -f "$lvl_file" ] && done_lv=$(head -1 "$lvl_file")
if [ "$used" -lt "$REARM_BELOW" ]; then
  [ -n "$done_lv" ] && : > "$lvl_file"
  exit 0
fi
step=""
if [ "$used" -ge "$FINAL_AT" ]; then case "$done_lv" in *2*) ;; *) step=2 ;; esac; fi
if [ -z "$step" ] && [ "$used" -ge "$NUDGE_AT" ]; then case "$done_lv" in *1*) ;; *) step=1 ;; esac; fi
[ -n "$step" ] || exit 0
if [ "$step" = 2 ]; then echo 12 > "$lvl_file"; else echo "${done_lv}1" > "$lvl_file"; fi

k=$((used / 1000))
tail_txt=""
if [ -n "$repo" ]; then
  have=""
  for f in $(ls -t "$docs_dir/$repo"-*.md 2>/dev/null | sed -n 1,3p); do have="$have
 - $f"; done
  [ -n "$have" ] && tail_txt="
Already present for this directory (refresh one of them rather than starting a new file):$have"
fi
if [ "$step" = 1 ]; then
  say "Context: ${k}k tokens; auto-compaction triggers around ${COMPACT_NEAR_K}k. The CLAUDE.md progress-doc rule is in force from now: before your next step, write or refresh ${doc} with the goal, decisions taken, finished vs open items, the precise next action and the relevant file paths.${tail_txt}"
else
  say "Context: ${k}k tokens, compaction (~${COMPACT_NEAR_K}k) is close. Put the final pre-compaction state into ${doc} right now: goal, decisions, finished vs open, precise next action, file paths. Whatever that file lacks may not survive.${tail_txt}"
fi
exit 0
