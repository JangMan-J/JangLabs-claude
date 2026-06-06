# Memory surfacing — autonomous build plan + progress (Phases 1–3)

<!-- handoff-scope: claude -->

**Status:** IN PROGRESS (autonomous `/goal`, started 2026-06-01). Phase 1 *engine + taxonomy data*
DONE; Phase 1 *hooks + settings + tests* DONE (2026-06-02) — built, registered, adversarially reviewed
(all findings fixed), 40 tests pass; **deploy posture = build-but-leave-off** (registered in the fragment
but not applied live; go-live = `./agent-harness.py install --apply`, kill-switch `<store>/.surface-disabled`).
Phases 2–3 DONE (2026-06-02, build-but-leave-off; live-deploy runbook below). Phase 4 (strict/obligation) not built. Resumable from here.

**What this is:** implementing the documented tag-routed memory-surfacing plan
(`2026-05-10-memory-system-overhaul.md` + `2026-05-11-...-rerun.md`, the chosen spec; comparison
verdict `2026-05-11-...-comparison.md`). Phase 0 (tag the corpus + `_tags.md` vocab) was already DONE.

## Autonomous scope + safety (decided, no further user feedback expected)
- **Build + deploy** (fail-open / advisory / narrow): Phase 1 `memory-write-guard` (scoped to
  `memory/*.md`, fails OPEN on error), `memory-catalog-refresh`, `memory-write-context`; Phase 2
  engine + `_tag_links.md`; Phase 3 advisory `memory-recall` (fail-open, `suppressOutput`, ≤3) +
  `MEMORY.md`→router.
- **Build but LEAVE OFF** (blocking / could deadlock a live session): the strict/obligation hooks
  (`memory-obligation-guard`, `memory-read-satisfy`, dismiss flow, strict-high-confidence mode) =
  Phase 4. NOT built here.
- **Out of scope autonomously:** Phase 4 tuning (needs real-session observation over time).
- Kill-switch `~/.claude/projects/-home-jangmanj/memory/.surface-disabled` checked by every hook.
- Test each component against a FIXTURE store (`MEMORY_SURFACE_DIR=/tmp/...`) before registering live.

## The 8 spec patches — resolved
1. **Path-tags** live in `_tag_links.md` `## Path Tags` (one taxonomy file; P4's `_path_tags.json` =
   the in-memory parsed form, not a separate file).
2. **Required-read policy (v1):** reading ANY ONE listed required memory satisfies the obligation;
   `maxRequiredReads=2` is the surface cap; `requireAllRequiredReads=false`. (Phase 4 only.)
3. **Perf budgets:** warm no-match ≤50ms (cap 100), warm match ≤150ms (cap 200), rebuild ≤300ms/≤200 mem.
4. **Token extraction:** per-tool (Bash split on `; && || |` no-exec; Read/Edit/Write basename+parents;
   WebSearch/WebFetch known-vocab ONLY, never free-text; mcp__ server/tool+args). Normalize to
   `^[a-z0-9][a-z0-9-]{1,39}$`; global stop-word list.
5. **Roulette frontmatter:** nested `metadata:` block + freshness fields (`lastReviewed/declineCount/
   nextEligible/originSessionId/node_type`) + unknown keys MUST round-trip losslessly.
6. **Markdown grammars frozen.** `_tag_links.md` = P6 backtick grammar (synonyms `` `a`=`b` ``,
   distinctions `` `a`!=`b` ``, path-tags `` `pat` -> `t1`,`t2` [@ strong|weak] [; reason] ``).
   `_tags.md` = **KEEP the LIVE faceted grammar** (`## domain|tool|method-pattern`, `- tag — gloss`
   em-dash, NO backticks) — P6's backtick `_tags.md` grammar is a DEFERRED migration (would break the
   Phase-0 corpus; needs user sign-off).
7. **Denylist:** `## Denylist` + `## Policy overrides` sections in `_tags.md` (`- tag — reason`).
   Seed: bug, config, file, linux, memory, setup, tool, fix, issue, note, problem, troubleshoot.
8. **queryHash:** `sha256(tool_name + \0 + sorted(canonicalTags).join(',') + \0 + normalized_strong_tokens)`,
   deterministic (no timestamp/session/random). Dedup TTL 900s; obligation identity.

## Hard constraints (apply to everything)
- Self-locate store from `$HOME` (`/`→`-`); NEVER hardcode the project key (`-home-jangman` broke before).
- Hooks quiet-on-success + cheap; the ONLY per-tool-call python is `memory_surface.py`, gated behind a
  shell cheap-gate in each hook.
- NEVER touch `permissions` in settings.json.
- Retrieval fails **OPEN**; taxonomy writes fail **CLOSED**.
- NO substring auto-surfacing on user-prompt text (rolled back; false positives at small N). Recall is
  PreToolUse tool-signal only; WebSearch/WebFetch match known vocab tokens only.
- Atomic writes (temp→fsync→os.replace / jq|sed→mv). Bodies NEVER cross into context — only ≤220-char
  descriptions; search reads `_memory_catalog.json`, not memory bodies.
- `_review_game.py` (Memory Roulette) must keep working unchanged; new engine mirrors its nested-metadata
  layout + field order, and additionally reads block-list `tags:` (a `_review_game.py` blind spot).
- **install.sh blocker — RESOLVED (2026-06-02).** The installer was ported to a single Python CLI
  `claude/agent-harness.py` (`install`/`remove`/`status`, dry-run default; supersedes install.sh+uninstall.sh).
  The settings-merge now reconciles at per-hook-command granularity within `(event,matcher)` — a hook can be
  added INTO an existing matcher block; a command already present in the event is never duplicated. Verified:
  old jq merge dropped 2 hooks added into the existing Edit|Write|MultiEdit block, new merge adds them. So
  Phase-1/3 hooks can now be registered directly into existing matcher blocks.
- `agent-harness.py` step 1b symlinks `claude/memory/*` into the store — EXCLUDES generated files
  (`_memory_catalog.json`, `_memory_surface_config.json`, plus dotfiles); only `_review_game.py`, `_tags.md`,
  `_tag_links.md` are lab-sourced. (Implemented in the port.)

## File manifest + status
**Phase 1 — engine + write-time validation** (deploy = build-but-leave-off; write-guard is the only blocker)
- [DONE] `claude/lib/memory_surface.py` — `validate` / `rebuild` (→ `_memory_catalog.json` atomic) /
  `check-write`. Frontmatter parse/generate mirrors `_review_game.py` + reads block-list tags;
  `_tags.md` faceted parser; `_tag_links.md` parser; denylist+override validation. VERIFIED on fixture
  (51 mem, 0 invalid, 0 round-trip structural drift; check-write allow/deny/deny correct).
- [DONE] `claude/memory/_tag_links.md` — seeded graph (7 synonyms, 22 path-tags, all active tags).
- [DONE] `claude/memory/_tags.md` — added `## Denylist` + `## Policy overrides`.
- [DONE] `claude/hooks/memory-write-context.sh` — PreToolUse Edit|Write|MultiEdit; on a memory-file write
  emit `additionalContext` with `_tags.md` excerpt; never blocks; quiet else.
- [DONE] `claude/hooks/memory-write-guard.sh` — PreToolUse Edit|Write|MultiEdit; cheap-gate to memory dir +
  `.surface-disabled`; Write→`check-write` full content (deny on rc2, FAIL CLOSED); Edit/MultiEdit validate
  new_string tags else FAIL OPEN; taxonomy edits validate+deny-on-error, allow bootstrap.
- [DONE] `claude/hooks/memory-catalog-refresh.sh` — PostToolUse Edit|Write|MultiEdit; cheap-gate; run
  `rebuild`; on post-write invalid taxonomy emit top-level `{"decision":"block","reason":...}`.
- [DONE] `claude/agent-harness.py` (replaces install.sh+uninstall.sh) — per-hook-command merge fix +
  generated-file exclusion from 1b. Parity-verified vs old bash; merge fix demonstrated.
- [DONE] `claude/settings.global.fragment.json` — add the 3 write-side hooks into existing
  Edit|Write|MultiEdit (Pre) + new PostToolUse Edit|Write|MultiEdit entries.
- [DONE] `claude/tests/memory_surface/test_phase1.py` (+ `test_hooks_phase1.sh`) — round-trip (all live mem), block-list tags,
  denylist, check-write, rebuild schema, invalid-omitted.

**Phase 2 — canonicalizer + search engine** (deploy = build-but-leave-off; dry-run/tests only) — DONE 2026-06-02 (commit 4602006)
- [DONE] extended `memory_surface.py`: `search` (§10 response), token extraction (§11, per-tool),
  synonym canonicalization, path-tag fnmatch (`**` suffix, `~` only), §12 ranking + confidence tiers +
  min-candidate, deterministic §15 queryHash; `link/unlink/add-tag/dismiss` mutators (atomic, fail-closed).
  Adversarially reviewed (5-agent); 22 findings fixed + pinned with 13 regression tests.
- [DONE-as-loader] `_memory_surface_config.json`: `load_config` + `DEFAULT_CONFIG` (mode=advisory) implemented;
  the live config FILE is a deploy artifact (defaults apply when absent), created at cutover — see runbook.
- [DONE] `claude/tests/memory_surface/test_phase2.py` — 45 cases (frozen fixtures, ranking math, queryHash
  determinism, bodies-never-loaded, mutator fail-closed, review-regression pins).

**Phase 3 — advisory recall + MEMORY.md router** (deploy = build-but-leave-off this session; runbook below) — DONE 2026-06-02
- [DONE] `claude/hooks/memory-recall.sh` — PreToolUse advisory; cheap-gate (kill-switch, memory-dir skip,
  pure-generic Bash) before python; runs `search`; emits `<memory-recall mode="advisory">` additionalContext;
  NEVER denies (Phase 4 = deny); dedup queryId ~15min; FAILS OPEN. 8 integration tests.
- [DONE-validator] `MEMORY.md` router: `validate_router` (§4) + `router-template` CLI + `router-check` CLI;
  5 tests. The LIVE MEMORY.md cutover is DEFERRED to deploy (converting it while recall is off would orphan
  memories) — see runbook.
- [DONE] `claude/CLAUDE.md.fragment` — `## Memory consultation` rewritten to the recall-block flow (deploy-coupled).
- [DONE] `claude/settings.global.fragment.json` — `memory-recall.sh` registered in 2 PreToolUse blocks.
- [DONE] `claude/tests/memory_surface/test_phase3.py` — 13 tests (hook integration via stdin JSON; advisory-only;
  never-deny; dedup; fail-open; router validator).

## Live-deploy runbook (build-but-leave-off → on; the user's call — recall spawns python per non-generic tool call, cheap-gated)
1. Build the catalog once: `python3 ~/.claude/projects/<key>/memory/… NO` → from the store dir run
   `MEMORY_SURFACE_DIR=<store> python3 <lab>/lib/memory_surface.py rebuild` (search fails closed if the catalog is absent).
2. Convert the index (back it up first): `cp <store>/MEMORY.md <store>/MEMORY.md.prerouter` then
   `python3 <lab>/lib/memory_surface.py router-template > <store>/MEMORY.md` (verify `router-check` rc 0).
3. (optional) write the live config: `{ "mode": "advisory" }` to `<store>/_memory_surface_config.json` (defaults already = advisory).
4. Apply the harness: from `claude/`, `./agent-harness.py install --apply` (deploys all 4 memory hooks + the fragment update), then restart Claude Code / `/reload-plugins`.
5. Kill-switch any time: `touch <store>/.surface-disabled` disables every memory hook instantly.
Phase 4 (NOT built): strict-high-confidence required mode + obligation-guard/read-satisfy — needs real-session observation first.

## Acceptance (per phase) — see the rerun spec §13–16 + each file's contract above. Key gates:
P1: round-trip preserves nested metadata byte-structure on all live memories; check-write deny/allow;
catalog atomic; `_review_game.py keep` still preserves tags. P2: golden fixtures match; queryHash
deterministic; bodies never read; warm budgets met. P3: advisory block emitted, never denies; router
≤40 lines; user-prompt text alone cannot trigger recall.
