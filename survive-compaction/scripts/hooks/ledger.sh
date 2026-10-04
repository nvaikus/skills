#!/bin/bash
# ledger.sh: PreCompact hook. One TSV row per compaction with the context size
# last seen by the statusline, for threshold calibration. Never blocks.
. "$(dirname "$0")/common.sh"
payload=$(cat)
IFS=$'\x1f' read -r sid aid atype tp cwd trigger <<EOF
$(fields session_id agent_id agent_type transcript_path cwd trigger)
EOF
keys=$(printf '%s' "$payload" | jq -r 'keys | join(",")' 2>/dev/null)
who="${atype}${aid:+($aid)}"; who="${who:-main}"
size="?"
[ -n "$sid" ] && [ -f "$state_dir/$(safe "$sid")" ] && size=$(head -1 "$state_dir/$(safe "$sid")")
if [ "$who" = main ] && is_num "$size" && [ "$size" -lt "$NUDGE_AT" ]; then
  # The main session cannot compact this small: a subagent did, and the payload
  # does not say which. Best guess: the one whose log changed last.
  who="teammate?:$(newest_subagent "$tp")"; size="n/a(main counter=$size)"
elif [ "$who" != main ]; then
  size="n/a(subagent)"
fi
mkdir -p "$state_dir"
book="$state_dir/compact-log.tsv"
[ -f "$book" ] || printf 'when\tsession\tagent\ttrigger\ttokens_at_compact\tcwd\tinput_keys\n' > "$book"
printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "${sid:0:8}" "$who" "${trigger:-?}" "$size" "$cwd" "$keys" >> "$book"
exit 0
