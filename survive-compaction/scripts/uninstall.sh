#!/bin/bash
# uninstall.sh: remove checkpoint hooks, registrations and runtime state.
# Leaves progress docs and the CLAUDE.md rule in place: remove those manually when no longer wanted.
set -e
cdir="$HOME/.claude"; dest="$cdir/hooks/checkpoint"; settings="$cdir/settings.json"
if [ -f "$settings" ]; then
  edit() { jq "$@" "$settings" > "$settings.tmp" && mv "$settings.tmp" "$settings"; }
  edit 'if .hooks then .hooks |= with_entries(
          .value |= map(select([.hooks[]?.command // ""] | any(contains("/hooks/checkpoint/")) | not))
        | select(.value != [])) else . end'
  case "$(jq -r '.statusLine.command // ""' "$settings")" in
    *checkpoint/meter.sh*)
      if [ -s "$dest/statusline.orig" ]; then edit --arg c "$(cat "$dest/statusline.orig")" '.statusLine.command = $c'
      else edit 'del(.statusLine)'; fi ;;
  esac
fi
for f in ctx-threshold compact-context compact-log compact-dump ctx-statusline; do
  grep -q 'checkpoint forward' "$cdir/hooks/$f.sh" 2>/dev/null && rm -f "$cdir/hooks/$f.sh"
done
rm -rf "$dest" "$cdir/.ctx-usage.d"
echo "Removed. Still there: progress docs in $cdir/progress, the rule in CLAUDE.md."
