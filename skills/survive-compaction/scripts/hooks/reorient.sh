#!/bin/bash
# reorient.sh: the post-compaction order, printed to stdout.
# Main session: SessionStart hook with matcher "compact".
# Subagent: watch.sh pipes the tool payload in and wraps the text as JSON.
. "$(dirname "$0")/common.sh"
payload=$(cat)
IFS=$'\x1f' read -r sid aid atype cwd <<EOF
$(fields session_id agent_id agent_type cwd)
EOF
repo=$(basename "${cwd:-$PWD}")
who="${atype:-$aid}"

show() { # show <file...>: newest first, with the modification time
  [ $# -gt 0 ] || { echo " - none"; return; }
  ls -t -- "$@" 2>/dev/null | head -5 | while IFS= read -r f; do
    printf ' - %s (modified %s)\n' "$f" "$(date -r "$f" +%H:%M 2>/dev/null)"
  done
}
mine=(); for f in "$docs_dir/$repo"-*.md; do [ -f "$f" ] && mine+=("$f"); done
fresh=(); while IFS= read -r f; do [ -n "$f" ] && fresh+=("$f"); done \
  < <(find "$docs_dir" -maxdepth 1 -type f -name '*.md' -mmin -720 2>/dev/null)

if [ -n "$who" ]; then
  echo "Compaction just happened inside agent ${who}: only the summary above remains. Before anything else, apply the CLAUDE.md progress-doc rule."
  echo "A progress-doc path given in your brief takes precedence over the lists below."
else
  echo "Compaction just happened. Before anything else, apply the CLAUDE.md progress-doc rule."
fi
echo "Docs for directory ${repo}, newest first:"
show ${mine[@]+"${mine[@]}"}
echo "Docs touched within the last 12 h:"
show ${fresh[@]+"${fresh[@]}"}
echo "Next:"
echo " 1. A listed file belongs to this task: open it, then bring it up to date from the summary."
echo " 2. None does: start a new ~/.claude/progress/${repo}-<task-slug>.md immediately, while the summary still holds the detail (goal, decisions, finished vs open, precise next action, file paths)."
echo " 3. ~/.claude/progress/compact/${sid:0:8}*-NN.md hold the raw summaries (saved by a hook): read-only reference, never edit them."
exit 0
