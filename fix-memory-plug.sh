#!/usr/bin/env bash
# fix-memory-plug.sh — surgically UNPLUG the memory base floor.
#
# Erases the `memory-base-floor.sh` SessionStart entry from ~/.claude/settings.json (and
# removes its hook symlink), so the <base-memory-floor> block stops being injected at the
# start of every session. Every OTHER hook (including the moshi SessionStart hook) and ALL
# permissions are left untouched.
#
# Why a dedicated script: agent-harness.py's `remove` strips the WHOLE harness; this pulls
# only the one plug. The `.surface-disabled` kill-switch disables EVERY memory hook; this
# disables only the base floor.
#
# Reversible — the entry still lives in settings.global.fragment.json, so:
#     cd ~/JangLabs/claude && ./agent-harness.py install --apply
# re-adds it. Idempotent: a no-op (rc 0) if already unplugged.
#
# Usage:  fix-memory-plug.sh           # erase (default)
#         fix-memory-plug.sh -n        # dry-run: show what would change, touch nothing
set -euo pipefail

DRY=0
case "${1:-}" in
  -n|--dry-run) DRY=1 ;;
  -h|--help) sed -n '2,21p' "$0"; exit 0 ;;
  "") : ;;
  *) echo "unknown arg: $1 (use -n for dry-run)" >&2; exit 2 ;;
esac

SETTINGS="${HOME}/.claude/settings.json"
HOOK_LINK="${HOME}/.claude/hooks/memory-base-floor.sh"
NEEDLE="memory-base-floor.sh"

command -v jq >/dev/null 2>&1 || { echo "jq is required" >&2; exit 1; }
[ -f "$SETTINGS" ] || { echo "no $SETTINGS — nothing to do"; exit 0; }

# Is the base-floor entry present under SessionStart? (traverse blocks -> hooks -> command)
if jq -e --arg n "$NEEDLE" \
      'any(.hooks.SessionStart[]?.hooks[]?; (.command // "") | contains($n))' \
      "$SETTINGS" >/dev/null 2>&1; then
  if [ "$DRY" -eq 1 ]; then
    echo "[dry-run] would remove the base-floor SessionStart entry from $SETTINGS:"
    jq --arg n "$NEEDLE" -r \
       '.hooks.SessionStart[].hooks[]? | select((.command // "")|contains($n)) | "    - " + .command' \
       "$SETTINGS"
  else
    ts=$(date +%Y%m%d-%H%M%S)
    cp -a "$SETTINGS" "${SETTINGS}.bak-${ts}"
    tmp=$(mktemp "${SETTINGS}.XXXXXX")
    trap 'rm -f "$tmp"' EXIT
    # Drop our command from every SessionStart block; drop blocks left empty; drop the
    # SessionStart key if it becomes empty. Nothing outside .hooks.SessionStart is touched.
    jq --arg n "$NEEDLE" '
      .hooks.SessionStart |= (
        map(.hooks |= map(select((.command // "") | contains($n) | not)))
        | map(select((.hooks | length) > 0))
      )
      | (if (.hooks.SessionStart // []) | length == 0 then del(.hooks.SessionStart) else . end)
    ' "$SETTINGS" > "$tmp"
    jq -e . "$tmp" >/dev/null            # sanity: output must be valid JSON
    mv "$tmp" "$SETTINGS"                 # atomic — survives Claude Code's live rewrites
    trap - EXIT
    echo "removed base-floor SessionStart entry from settings.json (backup: ${SETTINGS}.bak-${ts})"
  fi
else
  echo "base-floor SessionStart entry already absent in settings.json"
fi

# Remove the hook symlink so the file is fully unplugged (only if it is OUR symlink).
if [ -L "$HOOK_LINK" ]; then
  if [ "$DRY" -eq 1 ]; then echo "[dry-run] would remove symlink $HOOK_LINK"
  else rm -f "$HOOK_LINK"; echo "removed hook symlink $HOOK_LINK"; fi
elif [ -e "$HOOK_LINK" ]; then
  echo "note: $HOOK_LINK exists but is not a symlink — left in place" >&2
fi

[ "$DRY" -eq 1 ] && { echo "[dry-run] no changes made."; exit 0; }
echo "done — base memory floor unplugged. Restart Claude Code to apply."
echo "re-add later: cd ~/JangLabs/claude && ./agent-harness.py install --apply"
