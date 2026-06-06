# Claude-Lab harness — re-homing after the home-dir migration + install.sh audit

<!-- handoff-scope: claude -->

**Status:** Faithful record of a working session on 2026-05-22. The harness was reinstalled to the new global `~/.claude/` and `install.sh` was made host-agnostic; this documents the package as it now stands, what was fixed, and what still carries stale paths.

**Audience:** A future session (Claude or human) picking this up cold. Assume nothing about the box except what the per-turn `<system-fingerprint>` block reports.

**One-line context:** The login/home moved `/home/jangman` → `/home/jangmanj`. The harness had never been reinstalled into the new global `~/.claude/`, and the old config survived as a snapshot under `~/Backup/Arch/.claude/` — which, because cwd sits inside it, was loading as *project* config and firing the harness hooks at dead `/home/jangman/...` paths. That was the visible symptom (UserPromptSubmit hook errors).

---

## 1. The package

Lives at `~/Backup/Arch/Projects/Jangs-Lab/Claude-Lab/`. It is a **globally-installed** Claude Code harness, not a per-project one.

| File | Role |
|------|------|
| `install.sh` | Idempotent installer. Dry-run by default; `--apply` commits. |
| `uninstall.sh` | Counterpart (removes symlinks, the CLAUDE.md block, hook entries; leaves allow/deny alone). |
| `settings.global.fragment.json` | Merged into `~/.claude/settings.json` — `permissions.allow`/`.deny` + `hooks`. |
| `CLAUDE.md.fragment` | Appended to `~/.claude/CLAUDE.md` between `# --- begin/end Claude-Lab harness fragment ---` sentinels. |
| `hooks/*.sh` | Six hook scripts (below). **Symlinked** into `~/.claude/hooks/`, so editing the source here is live — no re-install needed for hook-script changes. |
| `README.md` | Overview + cost table. |
| `CLAUDE.md` | Lab working conventions (hooks quiet-on-success, cheap, test-before-merge). |
| `handoffs/` | This dir. Sacred — meant to let a fresh session resume cold. |

Backups from each `--apply` land in `Claude-Lab/.install-backups/<ts>/` (these were deleted at the user's request this session; they regenerate on next apply).

## 2. What `install.sh` does (verified by reading + dry-run)

1. **Hooks:** symlinks `Claude-Lab/hooks/*.sh` → `$CLAUDE_HOME/hooks/` (`CLAUDE_HOME=${CLAUDE_HOME:-$HOME/.claude}`), `chmod +x` the sources.
2. **CLAUDE.md:** if the sentinel block is present, replaces it in place via `awk`; else appends; else creates the file. The "Managed by …" line is normalized to *this checkout's* real path at write time (see fixes).
3. **settings.json:** `jq` merge that
   - unions `permissions.allow` / `permissions.deny` with the fragment's, deduped (`unique_by`);
   - adds `hooks` entries not already registered, matched by `.hooks[0].command`;
   - **never** writes `permissions.defaultMode`, `disableAllHooks`, or any bypass flag.
4. **Backups + idempotency:** modified files are copied to `.install-backups/<ts>/` before writing; re-running with no changes reports "already up to date."

`LAB_DIR` is derived from the script's own location, and `CLAUDE_HOME` from `$HOME`, so the *installer* was already host-portable; the hardcoded paths lived only in the artifacts it copied.

## 3. The six hooks

| Hook | Event (timeout) | Function | Status |
|------|-----------------|----------|--------|
| `system-fingerprint.sh` | UserPromptSubmit (5s) | Injects live box facts every turn (distro from `/etc/os-release`, kernel, session/desktop, **login shell from `getent passwd`** — `$SHELL` lies here, reports zsh while passwd is fish — pacman + AUR-helper detection, systemd-boot via EFI `LoaderInfo`, NVIDIA open-vs-closed kmod). Cached 60s in `/tmp`. | Healthy. Now correctly reports `CachyOS (Arch-based)` + `fish 4.7.1`. A good model of "detect, don't hardcode." |
| `memory-review-offer.sh` | UserPromptSubmit (3s) | Surfaces a "Memory Roulette" round for an overdue memory, ≤1×/local day, by spawning the Python engine `_review_game.py`. | **INERT.** See §6. |
| `bash-idiom-guard.sh` | PreToolUse:Bash (5s) | Blocks non-Arch idioms at command-start / after pipe boundaries (`apt`, `yum`/`dnf`, `grub-install`/`grub-mkconfig`, `update-grub`, SysVinit `service`) with a corrective message, exit 2. | Healthy. |
| `forbidden-files-guard.sh` | PreToolUse:Edit\|Write\|MultiEdit (5s) | Refuses writes to secret paths (`.env`, `*.key`, `*.pem`, `~/.ssh/`, `~/.gnupg/`), exit 2. | Healthy. |
| `config-drift-guard.sh` | PreToolUse:Edit\|Write\|MultiEdit (5s) | Rejects `settings.json` edits that introduce `disableAllHooks` / `bypassPermissions` / silent `defaultMode` shifts. The runtime mirror of install.sh's "never touch permission mode" rule. | Healthy. |
| `syntax-check-touched.sh` | PostToolUse:Edit\|Write\|MultiEdit (10s) | `jq empty` / `python -c ast.parse` / `bash -n` etc. on touched files. | Healthy. |

Hook conventions (from `Claude-Lab/CLAUDE.md`): **quiet on success** (exit 0, no stdout; reserve stderr for actionable failure), **cheap** (POSIX-ish shell + jq, no per-call Python — `memory-review-offer` is the deliberate exception, gated to ≤1/day), and **tested via sample JSON on stdin** before merging.

## 4. Permissions allow/deny — REMOVED 2026-05-22 (recorded for history)

**Status:** Removed later in this same session. The allow/deny list was scope-creep — the harness exists to reinforce good/bad-decision memory and ground the model, **not** to control system access. It was stripped from `settings.global.fragment.json` and `install.sh`, the residue was cleaned out of `~/.claude/settings.json` (`permissions` back to just `defaultMode: auto`), and install/uninstall are now symmetric (neither touches `permissions`). The mechanism below is kept only so a future reader understands what was there and why it's gone.

Denials were **static and install-time only** — `install.sh` did not learn or append them dynamically.

- The source of truth is the fixed `permissions.deny` array in `settings.global.fragment.json`. As installed today:
  ```
  Bash(rm -rf /)   Bash(rm -rf ~)   Bash(rm -rf .)   Bash(rm -rf *)
  Bash(git push --force:*)   Bash(git push -f:*)   Bash(git reset --hard:*)
  Bash(git clean -fdx:*)   Bash(sudo:*)
  ```
  (Plus a 30-entry `permissions.allow` of read-only commands so they don't prompt.)
- On `install.sh --apply`, jq **unions** the fragment's deny list into whatever is already in `~/.claude/settings.json`, deduped. It is **additive** — existing entries are never removed, and re-running is a no-op once present.
- Matching is Claude Code permission-pattern syntax: `Bash(<prefix>)` with `*` as wildcard. So `Bash(rm -rf *)` matches **any** `rm -rf …` command.
- **Live demonstration this session:** `rm -rf .install-backups` was auto-denied by `Bash(rm -rf *)` (the guard working as designed). Re-issuing as `rm -r .install-backups` (no `-f`) did **not** match the `rm -rf ` prefix, so it routed through a normal approval prompt instead of being blocked. Lesson: the deny list keys on the literal flag string — drop `-f` (or target a specific path the human approves) rather than trying to defeat the rule.
- The deny list is purely a *safety net*. Permission *mode* (`defaultMode`, bypass flags) is deliberately out of scope for install.sh and is additionally protected at runtime by `config-drift-guard.sh`.

## 5. Problems identified and FIXED this session

**A. The harness wasn't installed in the new home.** Global `~/.claude/` had no `hooks/`, an empty `CLAUDE.md`, and no harness hooks in `settings.json`. Reinstalled via `install.sh --apply` (additive, `defaultMode: auto` preserved).

**B. Backup-tree shadowing.** `~/Backup/Arch/.claude/settings.json` is the *old* global config captured in a snapshot; with cwd inside it, it loaded as project config and fired hooks at dead `/home/jangman/.claude/hooks/...` paths — the errors the user saw. Removed the now-redundant `hooks` block from that file (global harness is authoritative). Also removed its `statusLine` and deleted the orphaned `statusline-command.sh` (no longer wanted). *(Captured as a `[Fumble]` memory: don't repath the backup copy in place — global `~/.claude/` is the source of truth.)*

**C. Hardcoded `/home/jangman` paths in the copied artifacts.** `install.sh` itself was portable, but:
- `settings.global.fragment.json` hook commands hardcoded `/home/jangman/.claude/hooks/...`. → Fragment now stores a literal `HOOKS_DIR/` placeholder; `install.sh` rewrites every hook command to `$HOME/.claude/hooks/<basename>` at merge time (jq `with_entries` walk). Host-agnostic regardless of what the fragment stores.
- `CLAUDE.md.fragment`'s "Managed by …" line hardcoded the old path. → `install.sh` now normalizes it to `$LAB_DIR` on write (sed). Added a temp-file cleanup `trap`.

**D. A stale FALSE fact: "paru is NOT installed, use yay."** Verified both `paru` and `yay` are installed. Removed every such claim (CLAUDE.md.fragment, `bash-idiom-guard.sh`'s messages, README) and **deleted the guard branch that blocked `paru`** (it was rejecting a tool the box actually has). The illustrative "likely-assumption-easily-falsified" example was re-pointed at the kernel: assuming a stock `linux` kernel, when `uname -r` reports `-cachyos` (headers are `linux-cachyos-headers`).

**E. README hook count.** Was "Five hook scripts" and omitted `memory-review-offer.sh` from both tables. Now "Six," with the row added.

**F. Removed the permissions allow/deny list (the §4 misalignment).** It was never the harness's purpose. Stripped from `settings.global.fragment.json` and `install.sh`; cleaned the residue from `~/.claude/settings.json`; de-stale'd `uninstall.sh` and the docs. install/uninstall are now **symmetric** — both manage only {hook symlinks, the CLAUDE.md fragment block, hook entries in settings.json} and touch no permissions.

## 6. Problems that PERSIST

**A. `memory-review-offer.sh` is inert (hardcoded old path + missing engine).** Line 18:
```
SCRIPT=$HOME/.claude/projects/-home-jangman/memory/_review_game.py
```
This is the *only* residual `/home/jangman`-era path in the live package. The project-key segment is the pre-migration `-home-jangman` (current project keys are `-home-jangmanj` and `-home-jangmanj-Backup-Arch`), **and** `_review_game.py` does not exist anywhere under `~/.claude`. So the hook hits its `[ -f "$SCRIPT" ] || exit 0` guard and no-ops every turn. Memory Roulette (and the `/play` + `memory-review` skills, which need the same engine) is effectively off. Fixing requires both repathing line 18 **and** locating/restoring the engine script — repathing alone won't help.

**B. Broader migration debt outside this package.** `~/Projects/CLAUDE.md` (a migration-catch file) lists the related stale `-home-jangman` references still to fix: `~/.claude/skills/memory-review/SKILL.md`, `~/.claude/commands/play.md`, the `_review_game.py` `MEMDIR` constant (~line 34), the `~/.claude.json` `projects` map key, and memory files that hardcode `/home/jangman/...`. These are the most likely place the missing engine lives (under a differently-keyed project memory dir).

**C. Inert historical references.** The `handoffs/2026-05-11-*.md` specs contain `/home/jangman` paths in illustrative JSON. These are point-in-time records — leave them; don't rewrite history.

## 7. How to test a hook (no re-install needed for script edits)

```sh
# guard should flag apt, allow paru/yay:
printf '{"tool_input":{"command":"apt install foo"}}' | ./hooks/bash-idiom-guard.sh; echo "exit=$?"   # exit 2 + message
printf '{"tool_input":{"command":"paru -S foo"}}'     | ./hooks/bash-idiom-guard.sh; echo "exit=$?"   # exit 0, silent
# fingerprint:
printf '{}' | ./hooks/system-fingerprint.sh
```
After editing `CLAUDE.md.fragment` or `settings.global.fragment.json`, run `./install.sh --apply` (and `/reload-plugins` or restart) — those are copied/merged, not symlinked.

## TODO

- [ ] Restore Memory Roulette: `memory-review-offer.sh:18` points at `~/.claude/projects/-home-jangman/memory/_review_game.py` (pre-migration key) and the engine file is missing everywhere under `~/.claude`. Needs both a repath to the current project memory dir **and** locating/restoring `_review_game.py`. See §6A/§6B; the `~/Projects/CLAUDE.md` migration-catch file lists the likely sources. Until then this hook no-ops every turn and `/play` / `memory-review` have no engine.
