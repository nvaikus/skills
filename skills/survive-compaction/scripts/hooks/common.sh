# common.sh: sourced by every checkpoint hook. Paths, limits, small helpers.
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
state_dir="$HOME/.claude/.ctx-usage.d"     # shared contract: statuslines write <session> counters here
docs_dir="$HOME/.claude/progress"

# Absolute token limits (overridden by checkpoint.conf next to this file).
NUDGE_AT=110000       # first order: start/refresh the progress doc
FINAL_AT=145000       # second order: compaction is close
REARM_BELOW=60000     # below this both orders are armed again
COMPACT_NEAR_K=168    # where compaction is expected, in thousands (text only)
[ -f "$here/checkpoint.conf" ] && . "$here/checkpoint.conf"

safe() { printf '%s' "$1" | tr -c 'A-Za-z0-9-' '_'; }
is_num() { case "$1" in ''|*[!0-9]*) return 1 ;; esac; }

# fields <jq paths...>: one jq pass over $payload, values joined by \x1f
# (a non-blank separator, so empty fields survive `read`).
fields() {
  local expr="" p
  for p in "$@"; do expr="${expr:+$expr, }(.$p // \"\" | tostring)"; done
  printf '%s' "$payload" | jq -r "[$expr] | join(\"\u001f\")" 2>/dev/null
}

# newest_subagent <transcript_path>: name of the most recently written subagent log.
newest_subagent() {
  local f; f=$(ls -t "${1%.jsonl}/subagents/"*.jsonl 2>/dev/null | head -1)
  f=$(basename "${f:-unknown}" .jsonl); printf '%s' "${f#agent-}"
}
