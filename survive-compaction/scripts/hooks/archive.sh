#!/bin/bash
# archive.sh: PostCompact hook. Stores each generated summary as
# <session8>[-<agent>]-NN.md under ~/.claude/progress/compact/, pruning copies older
# than 14 days. Model-written progress docs are never touched.
. "$(dirname "$0")/common.sh"
payload=$(cat)
IFS=$'\x1f' read -r sid aid atype tp cwd trigger <<EOF
$(fields session_id agent_id agent_type transcript_path cwd trigger)
EOF
summary=$(printf '%s' "$payload" | jq -r '.compact_summary // empty' 2>/dev/null)
[ -n "$sid" ] && [ -n "$summary" ] || exit 0

tag=$(safe "${atype:-$aid}" | cut -c1-24)
if [ -z "$tag" ]; then
  size=$(head -1 "$state_dir/$(safe "$sid")" 2>/dev/null)
  # Too small for the main session to compact: label it with the likeliest subagent.
  if is_num "$size" && [ "$size" -lt "$NUDGE_AT" ]; then
    tag="teammate-$(safe "$(newest_subagent "$tp")" | cut -c1-30)"
  fi
fi

shelf="$docs_dir/compact"; mkdir -p "$shelf"
find "$shelf" -type f -name '*.md' -mtime +14 -delete 2>/dev/null
stem="${sid:0:8}${tag:+-$tag}"
last=0
for f in "$shelf/$stem"-[0-9][0-9].md; do
  [ -f "$f" ] || continue
  n=${f%.md}; n=${n##*-}; n=$((10#$n)); [ "$n" -gt "$last" ] && last=$n
done
nn=$(printf '%02d' $((last + 1)))
{
  echo "# Compaction summary $nn (session ${sid:0:8}${tag:+, agent $tag})"
  echo
  echo "- at: $(date '+%Y-%m-%d %H:%M:%S')"
  echo "- trigger: ${trigger:-?}"
  echo "- agent: ${tag:-main}"
  echo "- cwd: $cwd"
  echo "- session: $sid"
  echo
  echo "---"
  echo
  printf '%s\n' "$summary"
} > "$shelf/$stem-$nn.md"

# If the payload ever names the agent, tell watch.sh to deliver the order on its next tool call.
if [ -n "$aid" ]; then
  mkdir -p "$state_dir"; : > "$state_dir/$(safe "$sid")__$(safe "$aid").pending"
fi
exit 0
