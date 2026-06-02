#!/usr/bin/env bash
# UserPromptSubmit hook — workspace lab-scoping.
#
# When the session's working directory sits inside a multi-lab workspace (any
# ancestor directory holding a `.claude-workspace` marker), inject a short scope
# banner naming the active lab and its authoritative entry doc — but ONLY at the
# moment the active lab CHANGES from the previous turn. Silent on every other
# path: no marker found (most projects), unchanged lab, or unreadable input.
#
# This is the automation half of the workspace's context-rescoping mechanism;
# the documented protocol lives in the workspace-root CLAUDE.md. Stdout becomes
# injected context for the turn.
set -u

command -v jq >/dev/null 2>&1 || exit 0

input=$(cat 2>/dev/null) || exit 0
cwd=$(printf '%s' "$input" | jq -r '.cwd // empty' 2>/dev/null)
sid=$(printf '%s' "$input" | jq -r '.session_id // empty' 2>/dev/null)
[ -n "$cwd" ] || cwd=${PWD:-}
{ [ -n "$cwd" ] && [ -d "$cwd" ]; } || exit 0

# Walk upward to the workspace root (the directory holding the marker).
root=""
d=$cwd
while [ -n "$d" ] && [ "$d" != "/" ]; do
  if [ -e "$d/.claude-workspace" ]; then root=$d; break; fi
  d=$(dirname "$d")
done
[ -n "$root" ] || exit 0   # not inside a labs workspace → silent

# Active lab = first path component beneath the root ("" when sitting AT root).
case "$cwd" in
  "$root")   lab="" ;;
  "$root"/*) rel=${cwd#"$root"/}; lab=${rel%%/*} ;;
  *)         exit 0 ;;
esac
case "$lab" in .*) lab="" ;; esac   # dot-dirs (.git, .devcontainer) are not labs

ws=$(basename "$root")

# Per-session change detection: speak only when the lab differs from last turn.
state="/tmp/claude-labscope-${sid:-nosid}.last"
prev=""
[ -r "$state" ] && prev=$(cat "$state" 2>/dev/null)
printf '%s' "$lab" > "$state" 2>/dev/null || true
[ "$lab" = "$prev" ] && exit 0

# ---- emit the scope banner ----
if [ -z "$lab" ]; then
  printf '<workspace-scope>\n'
  printf 'Scope: **%s** workspace root (no single lab). Authority: ./CLAUDE.md.\n' "$ws"
  printf 'Every top-level non-dot directory is an independent nested repo (git submodule); cd into one and read its CLAUDE.md before editing there.\n'
  printf '</workspace-scope>\n'
  exit 0
fi

labdir="$root/$lab"
[ -d "$labdir" ] || exit 0

entry=""
for f in CLAUDE.md AGENTS.md README.md HANDOFF.md; do
  if [ -f "$labdir/$f" ]; then entry="$lab/$f"; break; fi
done

printf '<workspace-scope>\n'
printf 'Re-scoped to the **%s** lab (its own nested repo) of the %s workspace.\n' "$lab" "$ws"
if [ -n "$entry" ]; then
  printf 'Authority for work here: `%s` — read it first; its conventions OVERRIDE the workspace root for anything inside `%s/`.\n' "$entry" "$lab"
fi
printf 'This lab is its own repo; do not edit sibling labs from here.\n'
printf '</workspace-scope>\n'
exit 0
