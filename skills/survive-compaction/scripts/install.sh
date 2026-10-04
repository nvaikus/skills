#!/bin/bash
# install.sh: put the checkpoint hooks in place. Re-runnable: a second run only
# refreshes the scripts. Also migrates an older compact-guard setup.
set -e
src="$(cd "$(dirname "$0")" && pwd)"
cdir="$HOME/.claude"; dest="$cdir/hooks/checkpoint"; settings="$cdir/settings.json"
if ! command -v jq >/dev/null; then echo "checkpoint needs jq (macOS: brew install jq; Debian/Ubuntu: sudo apt-get install jq; Windows: winget install jqlang.jq)" >&2; exit 2; fi
mkdir -p "$dest" "$cdir/progress" "$cdir/.ctx-usage.d"
[ -f "$settings" ] || echo '{}' > "$settings"
cp "$settings" "$settings.checkpoint-backup"
edit() { jq "$@" "$settings" > "$settings.tmp" && mv "$settings.tmp" "$settings"; }

# 1. scripts
for f in "$src"/hooks/*.sh; do cp "$f" "$dest/"; chmod +x "$dest/$(basename "$f")"; done
echo "scripts   -> $dest"

# 2. limits (an existing, possibly tuned, file wins; old compact-guard values carry over)
conf="$dest/checkpoint.conf"; old_conf="$cdir/hooks/ctx-guard.conf"
if [ -f "$conf" ]; then
  echo "limits    kept $conf"
elif [ -f "$old_conf" ]; then
  ( . "$old_conf"; printf 'NUDGE_AT=%s\nFINAL_AT=%s\nREARM_BELOW=%s\nCOMPACT_NEAR_K=%s\n' "$T1" "$T2" "$RESET_BELOW" "$COMPACT_AT" ) > "$conf"
  echo "limits    carried over from $old_conf"
else
  w=$(jq -r '.autoCompactWindow // 200000' "$settings")
  printf 'NUDGE_AT=%d\nFINAL_AT=%d\nREARM_BELOW=%d\nCOMPACT_NEAR_K=%d\n' \
    $((w * 11 / 20)) $((w * 29 / 40)) $((w * 3 / 10)) $((w * 21 / 25000)) > "$conf"
  echo "limits    derived from autoCompactWindow=$w"
fi
rm -f "$old_conf"

# 3. hook registrations: drop compact-guard ones, add ours once
legacy='ctx-threshold\.sh|compact-context\.sh|compact-log\.sh|compact-dump\.sh'
edit --arg re "$legacy" '
  if .hooks then .hooks |= with_entries(
      .value |= map(select(any(.hooks[]?; (.command // "") | test($re)) | not))
    | select(.value != [])) else . end'
register() { # register EVENT MATCHER SCRIPT TIMEOUT
  edit --arg event "$1" --arg match "$2" --arg file "$3" --argjson secs "$4" '
    ("/hooks/checkpoint/" + $file) as $tail
    | {type: "command", command: ("\"$HOME/.claude" + $tail + "\""), timeout: $secs} as $entry
    | .hooks[$event] = (.hooks[$event] // [])
    | if any(.hooks[$event][].hooks[]?; (.command // "") | contains($tail)) then .
      else .hooks[$event] += [({hooks: [$entry]} + (if $match != "" then {matcher: $match} else {} end))] end'
}
register PostToolUse  ""      watch.sh    5
register SessionStart compact reorient.sh 5
register PreCompact   ""      ledger.sh   5
register PostCompact  ""      archive.sh  10
echo "hooks     PostToolUse, SessionStart(compact), PreCompact, PostCompact"

# 4. statusLine must feed the counter
cmd=$(jq -r 'if .statusLine then (.statusLine.command // "") else "" end' "$settings")
meter='"$HOME/.claude/hooks/checkpoint/meter.sh"'
use_meter() { edit --arg c "$meter" '.statusLine = ((.statusLine // {}) + {type: "command", command: $c})'; }
feeds=no
case "$cmd" in
  *ctx-statusline.sh*)   # compact-guard wrapper: keep what it wrapped
    [ -s "$cdir/hooks/ctx-statusline.inner" ] && [ ! -s "$dest/statusline.orig" ] &&
      cp "$cdir/hooks/ctx-statusline.inner" "$dest/statusline.orig"
    rm -f "$cdir/hooks/ctx-statusline.inner"; use_meter; feeds=migrated ;;
  *checkpoint/meter.sh*|*.ctx-usage.d*) feeds=yes ;;
  *) for part in $cmd; do   # a script named in the command may already write the counter
       part=$(printf '%s' "$part" | tr -d "\"'" | sed -e "s|^~|$HOME|" -e "s|\\\$HOME|$HOME|")
       if [ -f "$part" ] && grep -q '\.ctx-usage\.d' "$part"; then feeds=yes; fi
     done ;;
esac
case $feeds in
  yes) echo "statusline already stores the context size, untouched" ;;
  migrated) echo "statusline compact-guard wrapper replaced by meter.sh" ;;
  no) if [ -n "$cmd" ]; then echo "$cmd" > "$dest/statusline.orig"; fi; use_meter
      echo "statusline meter.sh${cmd:+ (renders the previous command from statusline.orig)}" ;;
esac

# 5. compact-guard script files: sessions started earlier still call them, so
#    they become one-line forwards to the new scripts
for pair in ctx-threshold:watch compact-context:reorient compact-log:ledger compact-dump:archive ctx-statusline:meter; do
  f="$cdir/hooks/${pair%%:*}.sh"
  [ -f "$f" ] || continue
  printf '#!/bin/bash\n# checkpoint forward: kept for sessions started before the switch; safe to delete later\nexec "$HOME/.claude/hooks/checkpoint/%s.sh"\n' "${pair##*:}" > "$f"
  chmod +x "$f"
done

# 6. the CLAUDE.md rule the orders point at
has_rule() { # CLAUDE.md itself or a file it imports with an @path line
  local f="$1" inc
  [ -f "$f" ] || return 1
  grep -q '^# Progress doc' "$f" && return 0
  for inc in $(sed -n 's/^@\([^ ]*\).*/\1/p' "$f"); do
    inc=${inc/#\~/$HOME}; case "$inc" in /*) ;; *) inc="$(dirname "$f")/$inc" ;; esac
    [ -f "$inc" ] && grep -q '^# Progress doc' "$inc" && return 0
  done
  return 1
}
if has_rule "$cdir/CLAUDE.md"; then
  echo "CLAUDE.md already carries the rule, untouched"
else
  { echo; cat "$src/../templates/claude-md-rule.md"; } >> "$cdir/CLAUDE.md"
  echo "CLAUDE.md rule added from templates/claude-md-rule.md"
fi
echo "Done. New sessions pick this up; running ones keep the hook set they started with."
