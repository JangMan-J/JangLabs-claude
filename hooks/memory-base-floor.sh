#!/usr/bin/env bash
# memory-base-floor.sh — SessionStart base-layer memory injection (the "base" half of a
# base + scoped memory environment, mirroring ~/.claude/CLAUDE.md + <repo>/CLAUDE.md).
#
# Claude Code keys each memory store to the git-repo root (or cwd outside a repo) and
# auto-loads only THAT store's MEMORY.md. So the box-brain router — the curated
# "always-relevant" floor — is natively loaded ONLY when the active repo IS $HOME. In
# every other session (any project / lab) that floor is absent and reaches Claude only
# via evidence-gated recall, which by design can miss always-on facts that have no
# per-tool-call trigger (e.g. the LIMINE-not-systemd-boot correction the fingerprint
# contradicts every turn). That is the seam this hook patches.
#
# It injects the box-brain MEMORY.md router as SessionStart additionalContext for every
# session WHOSE ACTIVE STORE IS NOT box-brain — making the curated floor present
# regardless of cwd. When the active store already IS box-brain (launched at $HOME), it
# stays silent so the floor is not double-loaded. SessionStart re-fires on
# startup/resume/clear/compact, so the floor self-heals after a compaction.
#
# Base layer ONLY: the bounded, curated router — never the catalog. The long tail stays
# demand-paged by memory-recall.sh. Cheap (no Python spawn), fails OPEN and silent on
# every error. Shares memory-recall's .surface-disabled kill-switch.
set -u

command -v jq >/dev/null 2>&1 || exit 0
[ -n "${HOME:-}" ] || exit 0

KEY=$(printf '%s' "$HOME" | tr '/' '-')
BRAIN="$HOME/.claude/projects/$KEY/memory"; BRAIN=${BRAIN%/}
ROUTER="$BRAIN/MEMORY.md"
[ -r "$ROUTER" ] || exit 0                              # no router -> nothing to floor
[ -e "$BRAIN/.surface-disabled" ] && exit 0            # shared kill-switch

input=$(cat)
cwd=$(printf '%s' "$input" | jq -r '.cwd // empty' 2>/dev/null || true)
[ -n "$cwd" ] || cwd="${PWD:-}"

# Replicate Claude Code's store keying: the active store is keyed to the git-repo root
# (or the cwd when not in a repo). If that key equals $HOME, box-brain is ALREADY the active
# store and natively loaded -> stay silent to avoid a double-load. When cwd is unknown we
# fall THROUGH to inject: missing-floor (the seam re-opening) is the costly direction; a
# stray double-load is merely cosmetic, so "uncertain" defaults to inject, not skip.
if [ -n "$cwd" ]; then
  root=$(git -C "$cwd" rev-parse --show-toplevel 2>/dev/null || printf '%s' "$cwd")
  # LEXICAL canonicalization (-sm: collapse ../trailing-slash but DO NOT resolve symlinks).
  # Claude Code keys by the literal path string, and the sibling memory-recall.sh locates its
  # store with realpath -sm for the same reason; resolving symlinks (-m) would collapse two
  # distinct literal keys and could WRONGLY SKIP, dropping the floor. Do not revert to -m.
  # See fumble-unverified-agent-cli-fix.
  canon() { realpath -sm -- "$1" 2>/dev/null || printf '%s' "${1%/}"; }
  [ "$(canon "$root")" = "$(canon "$HOME")" ] && exit 0
fi

# Base floor = the curated router, line-bounded like the native MEMORY.md load (first 200
# lines; the router-check validator already caps it far below that). Line-based so it can
# never cut a multibyte char mid-sequence and break jq's UTF-8 arg.
body=$(head -n 200 -- "$ROUTER" 2>/dev/null) || exit 0
[ -n "$body" ] || exit 0
# Defensive delimiter scrub: neutralize any literal wrapper tag in the (curated) router body
# so a stray line cannot forge an early </base-memory-floor> close. Parity with
# memory-recall.sh's mode="required"->"advisory" rewrite. Tag name only (no '/') so there is
# no bash pattern-escaping footgun, and it can't touch the wrapper tags added below.
body=${body//base-memory-floor/base-memory_floor}

floor=$(printf '<base-memory-floor store="%s">\nAlways-loaded box-brain memory floor — present in every session regardless of cwd; entry links below are relative to the store path above. The active repo memory store, if any, loads separately and adds to this. Tag-routed recall (memory-recall.sh) surfaces the rest on demand.\n\n%s\n</base-memory-floor>' "$BRAIN" "$body")

jq -cn --arg ctx "$floor" \
  '{hookSpecificOutput:{hookEventName:"SessionStart",additionalContext:$ctx}}'
exit 0
