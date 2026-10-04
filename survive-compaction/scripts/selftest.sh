#!/bin/bash
# selftest.sh: exercise the INSTALLED hooks with synthetic payloads, no live
# session needed. Uses a throwaway session id with tiny limits and removes
# everything it created. Exit 1 on any failure.
cdir="$HOME/.claude"; hk="$cdir/hooks/checkpoint"; st="$cdir/.ctx-usage.d"; settings="$cdir/settings.json"
sid="selftest$$x$(date +%s)"; aid="probe$$"; s8=${sid:0:8}
work=$(mktemp -d); tp="$work/$sid.jsonl"; : > "$tp"; mkdir -p "$work/$sid/subagents" "$st"
bad=0; pass() { echo "ok   $1"; }; fail() { echo "FAIL $1"; bad=1; }
tidy() {
  rm -rf "$work" "$st/$sid"* "$cdir/progress/compact/$s8"*
  [ -f "$st/compact-log.tsv" ] && grep -v "	$s8	" "$st/compact-log.tsv" > "$st/.tsv.$$" && mv "$st/.tsv.$$" "$st/compact-log.tsv"
}
trap tidy EXIT
expect() { case "$2" in *"$3"*) pass "$1" ;; *) fail "$1: got [$2]" ;; esac; }

for s in watch reorient ledger archive; do
  grep -q "hooks/checkpoint/$s.sh" "$settings" && pass "registered $s.sh" || fail "not registered: $s.sh"
done
echo "1000 2000 500" > "$st/$sid.override"
tool() { jq -cn --arg id "$sid" --arg log "$tp" --arg dir "$HOME" --argjson more "$1" \
  '$more + {tool_name: "Read", hook_event_name: "PostToolUse", cwd: $dir, transcript_path: $log, session_id: $id}'; }

echo 1500 > "$st/$sid"
expect "main: first order" "$(tool '{}' | "$hk/watch.sh")" "progress-doc rule is in force"
out=$(tool '{}' | "$hk/watch.sh"); [ -z "$out" ] && pass "main: first order only once" || fail "main: repeated: $out"
echo 2500 > "$st/$sid"
expect "main: second order" "$(tool '{}' | "$hk/watch.sh")" "compaction (~"

log="$work/$sid/subagents/agent-$aid.jsonl"
as_agent='{"agent_type":"probe","agent_id":"'"$aid"'"}'
echo '{"message":{"usage":{"cache_creation_input_tokens":0,"cache_read_input_tokens":400,"input_tokens":1100}},"type":"assistant"}' > "$log"
expect "subagent: first order" "$(tool "$as_agent" | "$hk/watch.sh")" "your brief gave you"
echo '{"subtype":"compact_boundary","type":"system"}' >> "$log"
expect "subagent: post-compaction order" "$(tool "$as_agent" | "$hk/watch.sh")" "inside agent probe"

ev() { jq -cn --arg id "$sid" --arg dir "$HOME" --argjson more "$1" '$more + {cwd: $dir, session_id: $id}'; }
ev '{"hook_event_name":"PostCompact","compact_summary":"selftest","trigger":"manual"}' | "$hk/archive.sh"
ls "$cdir/progress/compact/$s8"*-01.md >/dev/null 2>&1 && pass "archive: summary saved" || fail "archive: no file"
expect "reorient: order" "$(ev '{"source":"compact","hook_event_name":"SessionStart"}' | "$hk/reorient.sh")" "Compaction just happened"
ev '{"hook_event_name":"PreCompact","trigger":"manual"}' | "$hk/ledger.sh"
grep -q "	$s8	" "$st/compact-log.tsv" && pass "ledger: row written" || fail "ledger: no row"

[ $bad = 0 ] && echo "all checks passed" || { echo "checks FAILED"; exit 1; }
