# claude

A Claude Code harness for this box. A dozen hook scripts + a CLAUDE.md fragment + a settings.json fragment, installed globally to `~/.claude/`. Designed to be cheap per turn, narrow in scope, and easy to remove.

## What it does

| Layer | Mechanism | Hook event | Cost per turn |
|-------|-----------|------------|---------------|
| Input grounding | `system-fingerprint.sh` injects 9 lines of immutable box facts (kernel, pacman/paru, Limine, NVIDIA, etc.) | `UserPromptSubmit` | ~5ms cached |
| Workspace scoping | `lab-scope.sh` detects which lab of a `.claude-workspace`-marked tree (e.g. `~/JangLabs`) the cwd is in and injects a scope banner — only when the lab changes; silent elsewhere | `UserPromptSubmit` | ~5ms, no-op off-workspace |
| Pre-emptive redirection | `bash-idiom-guard.sh` blocks `apt`/`yum`/`grub-*`/`service` etc. with a corrective message | `PreToolUse` (Bash) | ~5ms when fires |
| Output verification | `syntax-check-touched.sh` runs `jq empty` / `python -c ast.parse` / `bash -n` etc. on touched files | `PostToolUse` (Edit/Write/MultiEdit) | 10–100ms when fires |
| Secret-write block | `forbidden-files-guard.sh` blocks writes to `.env`, `*.key`, `*.pem`, `~/.ssh/`, `~/.gnupg/` | `PreToolUse` (Edit/Write/MultiEdit) | ~5ms |
| Config drift block | `config-drift-guard.sh` rejects settings.json edits that introduce `disableAllHooks` / `bypassPermissions` / silent `defaultMode` shifts | `PreToolUse` (Edit/Write/MultiEdit) | ~5ms |
| Memory upkeep | `memory-review-offer.sh` surfaces a "Memory Roulette" review round for an overdue `~/.claude` memory (spawns the Python engine), capped at one offer per local day | `UserPromptSubmit` | ≤1 python spawn/day, no-op otherwise |
| Memory base layer | `memory-base-floor.sh` injects the box-brain `MEMORY.md` router (the curated always-relevant floor) into every session whose active store isn't box-brain, so the floor is present regardless of cwd — the *base* of a base+scoped memory env | `SessionStart` | 1 read+jq at session start; silent at `$HOME` |
| Handoff discovery | `handoff-index.sh` regenerates `<workspace>/.handoff_index` — every handoff across the labs' `.claude/handoffs/`, the tracked `claude/handoffs/` archive, and `~/.claude/handoffs/`, **grouped by scope** (cross-lab / per-lab / box / stale) read from each file's `<!-- handoff-scope: X -->` tag, path-inferred when untagged | `SessionStart` | 1 `find`+`grep` sweep at session start; no-op off-workspace |

A CLAUDE.md fragment adds: a verify-before-act rule, a memory-consultation rule, a `[Method]`/`[Fumble]` reflection-trigger rule for knowledge accretion, and an LSP-trust rule.

### Memory surfacing subsystem

A tag-routed memory system (the "ToolSearch pattern transposed to memories") layers on top of the box-brain store. It is **base + scoped**, mirroring how `~/.claude/CLAUDE.md` (global) + `<repo>/CLAUDE.md` (scoped) stack — because Claude Code keys each memory store to the **git-repo root** and auto-loads only that one store's `MEMORY.md`:

| Hook / part | Event | Role |
|---|---|---|
| `memory-base-floor.sh` | `SessionStart` | **Base layer** — inject the box-brain `MEMORY.md` router into every session whose active store isn't box-brain; silent (no double-load) when launched at `$HOME`. Re-fires on compact. |
| *(native)* `<repo>/memory/MEMORY.md` | startup | **Scoped layer** — the active repo's own store, auto-loaded by Claude Code, adds atop the floor. |
| `memory-recall.sh` | `PreToolUse` | **Demand-paging** — advisory `<memory-recall>` block of tag/tool-evidence-routed matches before a tool call; never denies, fails open, dedups ~15 min. |
| `memory-write-context.sh` / `memory-write-guard.sh` | `PreToolUse` | On writes to the store: surface write-time context, and validate tags against `_tags.md` (taxonomy writes fail **closed**). |
| `memory-catalog-refresh.sh` | `PostToolUse` | Rebuild `_memory_catalog.json` after a memory write. |
| `lib/memory_surface.py` | — | The engine: token extraction, semantic-graph canonicalization (`_tags.md` + `_tag_links.md`), ranking, catalog build, router validation. |

See `findings/memory-surfacing.md` and `handoffs/2026-06-01-memory-surfacing-build-plan.md` for the design.

## What it deliberately does NOT do

- No `Stop` hook running a polyglot repo verifier (codex's package did this; wrong cost shape for sysadmin/dotfiles work).
- No Python interpreter spawn per tool call (pure POSIX-ish shell + jq).
- No CI workflow / pre-commit / Makefile additions.
- No writes to `permissions` at all — not `allow`/`deny`, not `defaultMode`, not any bypass flag. Permission posture stays the user's.
- No MCP servers added.
- No skills pre-created. Skills should crystallize from observed Nth-session patterns, not anticipated ones.

## Install / uninstall

One CLI, `agent-harness.py` (Python 3, no `jq` dependency). Dry-run by default; pass
`--apply` to commit.

```sh
./agent-harness.py status            # what's currently installed (read-only)
./agent-harness.py install           # dry-run: shows what would change
./agent-harness.py install --apply   # commit
./agent-harness.py remove            # dry-run uninstall
./agent-harness.py remove --apply    # commit uninstall
```

Idempotent. `remove` reverses exactly what `install` adds — the symlinks, the CLAUDE.md
fragment block, and the hook entries in `settings.json` — and touches no permissions.
Backups land in `claude/.install-backups/<ts>/` (and `.uninstall-backups/<ts>/`). Restart
Claude Code (or run `/reload-plugins`) after applying.

The settings merge is per-hook-command within each `(event, matcher)`: a hook can be
added into an existing matcher block, and a command already registered is never
duplicated. Only the `hooks` block of `settings.json` is ever touched — `permissions`
stays the user's.

To disable **only** the base memory floor (not the whole harness, not every memory
hook), run `./fix-memory-plug.sh` — a narrow, reversible break-glass that removes just
the `memory-base-floor.sh` SessionStart entry and its symlink (`-n` to dry-run first).
Re-enable with `./agent-harness.py install --apply`. This is narrower than
`remove` (whole harness) and the `.surface-disabled` kill-switch (all memory hooks).

## Files

| File | Role |
|------|------|
| `hooks/system-fingerprint.sh` | UserPromptSubmit — 9-line box fingerprint, cached 60s |
| `hooks/lab-scope.sh` | UserPromptSubmit — inject a lab scope banner when the cwd's lab changes inside a `.claude-workspace`-marked tree; silent off-workspace |
| `hooks/bash-idiom-guard.sh` | PreToolUse(Bash) — block non-Arch idioms |
| `hooks/syntax-check-touched.sh` | PostToolUse(Edit/Write) — narrow syntax verification |
| `hooks/forbidden-files-guard.sh` | PreToolUse(Edit/Write) — block secret-path writes |
| `hooks/config-drift-guard.sh` | PreToolUse(Edit/Write) — block settings weakening |
| `hooks/memory-review-offer.sh` | UserPromptSubmit — offer a Memory Roulette round for an overdue memory, ≤1×/day |
| `hooks/memory-base-floor.sh` | SessionStart — inject the box-brain MEMORY.md router as a base memory floor when the active store isn't box-brain; silent at `$HOME` |
| `hooks/handoff-index.sh` | SessionStart — regenerate `<workspace>/.handoff_index` (all handoffs across labs + `~/.claude/handoffs/`, grouped by scope from each file's `<!-- handoff-scope: X -->` tag, path-inferred when untagged); silent off a `.claude-workspace`-marked tree |
| `hooks/memory-recall.sh` | PreToolUse — advisory tag-routed memory recall before a tool call; never denies, fails open |
| `hooks/memory-write-context.sh` | PreToolUse — surface context on writes to the memory store |
| `hooks/memory-write-guard.sh` | PreToolUse — validate memory/taxonomy writes (tags vs `_tags.md`); taxonomy fails closed |
| `hooks/memory-catalog-refresh.sh` | PostToolUse — rebuild `_memory_catalog.json` after a memory write |
| `lib/memory_surface.py` | Memory-surfacing engine (token extraction, ranking, catalog build, router validation) |
| `memory/_tags.md`, `memory/_tag_links.md` | Tag vocabulary + semantic graph; symlinked into the box-brain store |
| `CLAUDE.md.fragment` | Appended to `~/.claude/CLAUDE.md` between sentinels |
| `settings.global.fragment.json` | Merged into `~/.claude/settings.json` (hooks only) |
| `memory/_review_game.py` | Memory Roulette engine; symlinked into the box-brain memory store by agent-harness.py (self-locates its store from `$HOME`) |
| `agent-harness.py` | Idempotent install / remove / status CLI (dry-run by default; supersedes the former `install.sh`+`uninstall.sh`) |
| `fix-memory-plug.sh` | Break-glass: unplug ONLY the `memory-base-floor.sh` SessionStart hook (and its symlink) from `settings.json`, leaving every other hook and all permissions intact. Idempotent; `--dry-run`/`--help`; re-enable via `agent-harness.py install --apply` |

## Iteration

Edit the source under `claude/hooks/` directly — the symlinks point here, so changes are live. Re-run `./agent-harness.py install --apply` only when changing the CLAUDE.md fragment or settings.json shape.

## Known limitations

- `bash-idiom-guard.sh` matches at command-start or after pipe boundaries, but a deeply-nested heredoc or process substitution containing `apt install` could slip past. The cost-of-false-negative here is "Claude tries `apt`, gets `command not found`, learns" — acceptable.
- `config-drift-guard.sh` pattern-matches the proposed file content. A semantically equivalent edit using JSON whitespace tricks could evade it. Not worth defending against (no one types `disableAllHooks: true` accidentally).
- The `system-fingerprint` cache lives in `/tmp` and survives reboots' worth of context, but `/tmp` is tmpfs on most setups so it does NOT survive reboot. Acceptable.
