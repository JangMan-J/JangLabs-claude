#!/usr/bin/env bash
# handoff-index.sh — SessionStart regenerator for the workspace handoff index.
#
# Handoffs are fragmented BY DESIGN: the session-handoff skill writes each one to
# <launch-cwd>/.claude/handoffs/, so a handoff lands in whichever lab (or the workspace
# root, or $HOME) the session was launched from — and .claude/ is globally git-ignored,
# so they are untracked scratch. That locality is good (a lab's handoffs stay with the
# lab) but it scatters them across many dirs. This hook keeps ONE discoverable index at the
# workspace root: .handoff_index, listing each handoff's real path GROUPED BY SCOPE.
#
# Scope is classified BY CONTENT, not directory: each handoff declares its bucket with a
# '<!-- handoff-scope: X -->' tag inside the file (X = cross-lab | <lab> | box | stale),
# set after reading it — a handoff's real subject can differ from where it physically sits
# (e.g. a box-level tool handoff parked under a lab dir). Untagged files fall back to a
# path guess, flagged '(inferred)' so the index shows it was not declared.
#
# It is a workspace coordinator file (a dot-file at the root), so it honors the
# "non-dot ⇒ submodule" invariant without an exception. The hook installs globally but is
# a silent no-op off the JangLabs-style workspace: it walks UP from the session cwd to the
# `.claude-workspace` marker (same mechanism as lab-scope.sh) and does nothing if absent.
#
# Cheap: pure shell + find, no Python, no jq dependency. SessionStart fires once per
# session (startup/resume/clear/compact), not per tool call. Writes a file as a side
# effect; emits NO additionalContext. Fails OPEN and silent on every error.
set -u

# --- locate the workspace root by walking up to the marker (silent no-op if not found) ---
# Read cwd from the SessionStart JSON if jq is present; else fall back to $PWD. We avoid a
# hard jq dependency here (unlike memory hooks) because this hook needs no JSON output.
input=$(cat 2>/dev/null || true)
cwd=""
if command -v jq >/dev/null 2>&1 && [ -n "$input" ]; then
  cwd=$(printf '%s' "$input" | jq -r '.cwd // empty' 2>/dev/null || true)
fi
[ -n "$cwd" ] || cwd="${PWD:-}"
[ -n "$cwd" ] || exit 0

root=""
dir=$cwd
while [ -n "$dir" ] && [ "$dir" != "/" ]; do
  if [ -e "$dir/.claude-workspace" ]; then root=$dir; break; fi
  dir=$(dirname -- "$dir")
done
[ -n "$root" ] || exit 0                                   # off-workspace -> nothing to do

index="$root/.handoff_index"
tmp="$index.tmp.$$"

# --- collect handoff files from every place the skill (or legacy convention) puts them ---
# Search roots, in this order: the workspace root's own .claude/handoffs (cross-lab HOs);
# every top-level non-dot child's .claude/handoffs (per-lab scratch) AND legacy handoffs/
# (the cited, tracked design archive in claude/); and ~/.claude/handoffs (sessions launched
# from $HOME). Each candidate dir is optional — missing ones are simply skipped.
emit_dir() {  # $1 = dir to scan -> emit each handoff file path, one per line
  [ -d "$1" ] || return 0
  # -maxdepth 1: handoffs are flat files in these dirs. Match .md and .jsonl session logs.
  find "$1" -maxdepth 1 -type f \( -name '*.md' -o -name '*.session.jsonl' \) 2>/dev/null
}

# scope_of <file> <lab-guess> -> echoes the scope bucket for this handoff.
# Classification is BY CONTENT first: a '<!-- handoff-scope: X -->' tag inside the file
# (set deliberately after reading it) wins — directory structure can lie (e.g. a box-level
# cockpit handoff that happens to sit under a lab dir). Only when untagged do we FALL BACK
# to a path guess, suffixed '?' so the index visibly flags it as inferred, not declared.
# Buckets: cross-lab | <lab name> | box | stale.
scope_of() {
  st=$(grep -m1 -oE '<!-- handoff-scope: [a-z-]+ -->' "$1" 2>/dev/null \
        | grep -oE ': [a-z-]+ ' | tr -d ': ')
  if [ -n "$st" ]; then printf '%s' "$st"; else printf '%s?' "$2"; fi
}

# Gather every handoff as "scope<TAB>name<TAB>realpath", classified per scope_of.
TAB=$(printf '\t')
rows=$(
  emit_dir "$root/.claude/handoffs" | while IFS= read -r f; do
    [ -n "$f" ] && printf '%s\t%s\t%s\n' "$(scope_of "$f" cross-lab)" "$(basename -- "$f")" "$f"
  done
  for child in "$root"/*/; do
    child=${child%/}; base=$(basename -- "$child")
    case "$base" in .*) continue ;; esac                   # skip dot-dirs (not labs)
    { emit_dir "$child/.claude/handoffs"; emit_dir "$child/handoffs"; } | while IFS= read -r f; do
      [ -n "$f" ] && printf '%s\t%s\t%s\n' "$(scope_of "$f" "$base")" "$(basename -- "$f")" "$f"
    done
  done
  [ -n "${HOME:-}" ] && emit_dir "$HOME/.claude/handoffs" | while IFS= read -r f; do
    [ -n "$f" ] && printf '%s\t%s\t%s\n' "$(scope_of "$f" box)" "$(basename -- "$f")" "$f"
  done
)
rows=$(printf '%s\n' "$rows" | grep -v '^[[:space:]]*$' | sort -u)

# render_group <bucket-label> <exact-bucket-name> — print a section if non-empty.
# Match by stripping any trailing '?' (the inferred marker) from the scope column and
# comparing for EQUALITY — avoids ERE-escaping footguns with the literal '?' in scopes.
render_group() {
  body=$(printf '%s\n' "$rows" | awk -F"$TAB" -v want="$2" \
           '{s=$1; sub(/\?$/,"",s)} s==want' | sort -rt "$TAB" -k2,2)
  [ -n "$body" ] || return 0
  printf '\n## %s\n' "$1"
  printf '%s\n' "$body" | while IFS="$TAB" read -r sc name f; do
    [ -n "$f" ] || continue
    # Portable display path: workspace-relative under root, ~-relative under $HOME, else absolute.
    case "$f" in
      "$root"/*)              shown=${f#"$root"/} ;;
      "${HOME:-/dev/null}"/*) shown="~/${f#"$HOME"/}" ;;
      *)                      shown=$f ;;
    esac
    # Mark inferred (untagged, path-guessed) scopes with a trailing '(inferred)'.
    case "$sc" in *\?) note='  # inferred from path — untag/retag to confirm' ;; *) note='' ;; esac
    printf '%s\t%s%s\n' "$name" "$shown" "$note"
  done
}

{
  printf '# .handoff_index — generated by claude/hooks/handoff-index.sh on SessionStart.\n'
  printf '# Do not edit by hand; rewritten every session. Grouped by SCOPE, classified by a\n'
  printf '# "<!-- handoff-scope: X -->" tag inside each file (set after reading it); files\n'
  printf '# with no tag are path-inferred and flagged "(inferred)". To reclassify a handoff,\n'
  printf '# edit its in-file tag (X = cross-lab | <lab> | box | stale), not this index.\n'
  printf '# Handoffs are git-ignored scratch under <lab>/.claude/handoffs/, the workspace\n'
  printf '# root .claude/handoffs/, or ~/.claude/handoffs/; the tracked claude/handoffs/ is a\n'
  printf '# cited design archive. Each line: filename<TAB>path.\n'

  render_group 'Cross-lab (workspace-spanning)' 'cross-lab'
  # Per-lab groups, in the workspace's canonical lab order.
  for lab in agent claude jangsjedi jangsjyro proton; do
    render_group "Lab: $lab" "$lab"
  done
  render_group 'Box / unspecified (not a single lab)' 'box'
  render_group 'Stale (superseded — retain for history)' 'stale'
} > "$tmp" 2>/dev/null || { rm -f "$tmp" 2>/dev/null; exit 0; }

# Atomic replace (parity with the settings.json jq+mv discipline). mv is atomic within one
# filesystem; the index and its tmp share the workspace root, so this never races a reader
# into a half-written file.
mv -f "$tmp" "$index" 2>/dev/null || rm -f "$tmp" 2>/dev/null
exit 0
