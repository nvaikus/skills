#!/bin/bash
# meter.sh: statusLine command. Stores the session's context size
# (context_window.total_input_tokens) for watch.sh, then renders the status line
# that was configured before install (statusline.orig), or a one-line default.
. "$(dirname "$0")/common.sh"
payload=$(cat)
IFS=$'\x1f' read -r sid used model pct <<EOF
$(fields session_id context_window.total_input_tokens model.display_name context_window.used_percentage)
EOF
if [ -n "$sid" ] && is_num "$used"; then
  counter="$state_dir/$(safe "$sid")"
  if [ ! -f "$counter" ]; then   # new session: housekeeping, once
    mkdir -p "$state_dir"
    find "$state_dir" -type f ! -name '*.tsv' -mtime +7 -delete 2>/dev/null
  fi
  printf '%s\n' "$used" > "$counter"
fi
if [ -s "$here/statusline.orig" ]; then
  printf '%s' "$payload" | bash -c "$(cat "$here/statusline.orig")"
else
  is_num "$used" || used=0
  printf '%s | ctx %sk%s\n' "$model" "$((used / 1000))" "${pct:+ (${pct%%.*}%)}"
fi
