# claude

A Claude Code harness for this box. Seven hook scripts + a CLAUDE.md fragment + a settings.json fragment, installed globally to `~/.claude/`. Designed to be cheap per turn, narrow in scope, and easy to remove.

## What it does

| Layer | Mechanism | Hook event | Cost per turn |
|-------|-----------|------------|---------------|
| Input grounding | `system-fingerprint.sh` injects 9 lines of immutable box facts (kernel, pacman/yay, systemd-boot, NVIDIA, etc.) | `UserPromptSubmit` | ~5ms cached |
| Workspace scoping | `lab-scope.sh` detects which lab of a `.claude-workspace`-marked tree (e.g. `~/JangLabs`) the cwd is in and injects a scope banner — only when the lab changes; silent elsewhere | `UserPromptSubmit` | ~5ms, no-op off-workspace |
| Pre-emptive redirection | `bash-idiom-guard.sh` blocks `apt`/`yum`/`grub-*`/`service` etc. with a corrective message | `PreToolUse` (Bash) | ~5ms when fires |
| Output verification | `syntax-check-touched.sh` runs `jq empty` / `python -c ast.parse` / `bash -n` etc. on touched files | `PostToolUse` (Edit/Write/MultiEdit) | 10–100ms when fires |
| Secret-write block | `forbidden-files-guard.sh` blocks writes to `.env`, `*.key`, `*.pem`, `~/.ssh/`, `~/.gnupg/` | `PreToolUse` (Edit/Write/MultiEdit) | ~5ms |
| Config drift block | `config-drift-guard.sh` rejects settings.json edits that introduce `disableAllHooks` / `bypassPermissions` / silent `defaultMode` shifts | `PreToolUse` (Edit/Write/MultiEdit) | ~5ms |
| Memory upkeep | `memory-review-offer.sh` surfaces a "Memory Roulette" review round for an overdue `~/.claude` memory (spawns the Python engine), capped at one offer per local day | `UserPromptSubmit` | ≤1 python spawn/day, no-op otherwise |

A CLAUDE.md fragment adds: a verify-before-act rule, a memory-consultation rule, a `[Method]`/`[Fumble]` reflection-trigger rule for knowledge accretion, and an LSP-trust rule.

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
| `CLAUDE.md.fragment` | Appended to `~/.claude/CLAUDE.md` between sentinels |
| `settings.global.fragment.json` | Merged into `~/.claude/settings.json` (hooks only) |
| `memory/_review_game.py` | Memory Roulette engine; symlinked into the box-brain memory store by agent-harness.py (self-locates its store from `$HOME`) |
| `agent-harness.py` | Idempotent install / remove / status CLI (dry-run by default; supersedes the former `install.sh`+`uninstall.sh`) |

## Iteration

Edit the source under `claude/hooks/` directly — the symlinks point here, so changes are live. Re-run `./agent-harness.py install --apply` only when changing the CLAUDE.md fragment or settings.json shape.

## Known limitations

- `bash-idiom-guard.sh` matches at command-start or after pipe boundaries, but a deeply-nested heredoc or process substitution containing `apt install` could slip past. The cost-of-false-negative here is "Claude tries `apt`, gets `command not found`, learns" — acceptable.
- `config-drift-guard.sh` pattern-matches the proposed file content. A semantically equivalent edit using JSON whitespace tricks could evade it. Not worth defending against (no one types `disableAllHooks: true` accidentally).
- The `system-fingerprint` cache lives in `/tmp` and survives reboots' worth of context, but `/tmp` is tmpfs on most setups so it does NOT survive reboot. Acceptable.
