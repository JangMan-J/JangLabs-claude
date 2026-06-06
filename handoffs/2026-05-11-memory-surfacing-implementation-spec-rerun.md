# Memory surfacing implementation specification - rerun

<!-- handoff-scope: claude -->

**Status:** Implementation spec v2 candidate from arbiter rerun.  
**Created:** 2026-05-11.  
**Source overview:** `Claude-Lab/handoffs/2026-05-10-memory-system-overhaul.md`.  
**Prior output for comparison:** `Claude-Lab/handoffs/2026-05-11-memory-surfacing-implementation-spec.md`.  
**Rerun agents:** Claude CLI default strong Opus configuration, max effort; Codex CLI default model (`gpt-5.5`), xhigh reasoning.  
**Target corpus:** `~/.claude/projects/-home-jangman/memory/`.  
**Target harness:** `Claude-Lab/` hooks, settings fragment, install flow, and tests.

This document is a fresh implementation specification for the erosion-resistant memory surfacing tool. It preserves the rough overview's central rule:

> Unbounded memory data may live on disk. Only bounded, ranked, tool-call-routed summaries may cross into model context.

---

## 1. Product contract

When an AI agent is about to use a tool, a hook extracts concrete signals from that tool call, resolves those signals through a user-curated tag vocabulary and semantic link/unlink graph, and surfaces a capped list of relevant memory summaries.

For high-confidence matches, the system creates a **memory obligation**: the model must read or explicitly dismiss the surfaced memory before continuing on the same tool-call path. This is the structural "MUST-use" layer.

The hook never auto-loads memory bodies.

### Goals

- Replace always-loaded prose-index skimming with tool-call-triggered recall.
- Keep all prompt-visible memory surfaces hard-capped.
- Let the memory corpus and tag graph grow without prompt erosion.
- Make tag curation human-readable and deliberately editable.
- Enforce tag consistency at memory write time.
- Preserve Memory Roulette fields and behavior.
- Support Claude Code first while defining a host-neutral `MemorySearch` contract.

### Non-goals

- No embeddings or vector database.
- No prompt-substring retrieval.
- No automatic memory body loading.
- No automatic tag invention.
- No automatic semantic merging or splitting.
- No ML ranker.
- No background daemon in v1.

---

## 2. Hard caps

| Surface | Cap |
|---|---:|
| Recall results per event | 3 memories |
| Required reads per obligation | 2 memories |
| Description characters per result | 220 hard cap, 150 target |
| Recall block size | 4000 chars hard cap, 1600 target |
| Full bodies auto-loaded by hook | 0 |
| Tags per memory | 8 hard cap, 3-5 target |
| Active tag vocabulary | 200 tags hard cap |
| Tag vocabulary excerpt shown on write errors | 200 lines hard cap |
| Always-loaded `MEMORY.md` after cutover | 40 nonblank lines hard cap, 20 target |
| Obligation TTL | 30 minutes |

If a cap would be exceeded, drop lower-ranked results or truncate descriptions. Never spill bodies into context.

---

## 3. File layout

Authoritative corpus data lives beside the memory corpus:

```text
~/.claude/projects/-home-jangman/memory/
  MEMORY.md
  *.md
  _review_game.py
  _tags.md
  _tag_links.md
  _memory_catalog.json
  _memory_surface_config.json
```

Harness code lives in `Claude-Lab`:

```text
Claude-Lab/
  hooks/
    memory-recall.sh
    memory-obligation-guard.sh
    memory-read-satisfy.sh
    memory-write-context.sh
    memory-write-guard.sh
    memory-catalog-refresh.sh
  lib/
    memory_surface.py
  tests/
    memory_surface/
```

Design decision:

- `_tags.md` and `_tag_links.md` are source-of-truth because the user must be able to read and curate them quickly.
- `_memory_catalog.json` is generated because hooks need cheap structured lookup.
- Hook code is shared across projects; taxonomy state belongs to the corpus it indexes.

---

## 4. `MEMORY.md` role

`MEMORY.md` is always loaded by Claude Code memory behavior, so it must stop being a line-per-memory index once recall ships.

After Phase 3, `MEMORY.md` becomes a compact router:

```md
# Memory router

Project memories are surfaced by the tool-call memory recall hook.
Do not skim this directory by habit.

When a `<memory-recall>` block appears, use it as required project context.
Read full memory files only when the surfaced summary is action-changing.

When writing memories, use tags from `_tags.md`; add a genuinely new tag there first.
```

Validation rules after cutover:

- warn above 20 nonblank lines
- fail above 40 nonblank lines unless `MEMORY_SURFACE_ALLOW_LONG_INDEX=1`
- fail if it contains a line per memory file

Phase 0 may leave the existing index in place while data is seeded. Phase 3 must convert it.

---

## 5. Memory frontmatter

Every non-special memory file must have frontmatter:

```yaml
---
name: KRDP abandoned on this box - Sunshine+Moonlight used instead
description: Plasma 6.6.4 krdp has KCM cert-path and codec bugs; this box uses Sunshine + Moonlight instead.
type: project
tags: [kde, plasma, krdp, remote-desktop, sunshine, moonlight]
originSessionId: d0975ccc-17e4-4dc4-a0cb-17d6820081c8
lastReviewed: 2026-05-09
declineCount: 0
nextEligible: 2026-08-01
---
```

Required fields:

- `name`
- `description`
- `type`
- `tags`

Optional fields preserved:

- `originSessionId`
- `lastReviewed`
- `declineCount`
- `nextEligible`
- unknown fields already tolerated by `_review_game.py`

Tag syntax:

```yaml
tags: [kde, plasma, krdp]
```

Rules:

- one-line flow-list only in v1
- token regex: `^[a-z0-9][a-z0-9-]{1,39}$`
- lowercase ASCII
- hyphens, not underscores
- all tags must be active in `_tags.md`, or declared as retired aliases in `_tag_links.md`
- memory bodies are never surfaced by hooks

---

## 6. Tag vocabulary

File:

```text
~/.claude/projects/-home-jangman/memory/_tags.md
```

Format:

```md
# Memory Tag Vocabulary

## Policy

Tags name projects, subsystems, tools, hardware, protocols, or recurring failure domains.
Avoid generic tags such as `linux`, `config`, `tool`, `bug`, `file`, and `misc`.

## Active Tags

- `kde` - KDE desktop stack and Plasma-adjacent configuration on this box.
- `plasma` - Plasma shell, KCM, and session behavior, not every KDE application.
- `krdp` - KDE Remote Desktop server, KCM module, and krdpserverrc behavior.
- `remote-desktop` - RDP, Sunshine, Moonlight, and remote GUI access.
- `zsh` - zsh startup files and shell-specific behavior.

## Deprecated Tags

- `remote-access-ui` -> `remote-desktop` - Old name retained for historical frontmatter compatibility.
```

Parser rules:

- parse only bullets matching ``- `tag-slug` - description`` under `Active Tags`
- parse only bullets matching ``- `old` -> `new` - reason`` under `Deprecated Tags`
- descriptions must be 6-32 words
- active tag count must be <= 200
- deprecated replacements must point to active tags
- generic tags are rejected unless the policy section has an explicit `Allow generic:` line naming the tag and reason

Write-time behavior:

- When a memory write uses an unknown tag, `memory-write-guard.sh` denies with closest active matches and a capped `_tags.md` excerpt.
- A genuinely new tag must be added to `_tags.md` before it can be used in memory frontmatter.

---

## 7. Semantic link/unlink graph

File:

```text
~/.claude/projects/-home-jangman/memory/_tag_links.md
```

Format:

```md
# Semantic Tag Links

## Synonyms

- `kwin` = `plasma-compositor` - KWin is the Plasma compositor for retrieval.
- `claude-code` = `anthropic-claude-cli` - This corpus uses claude-code as the canonical tag.

## Distinctions

- `kde-wayland` != `kde-x11` - Wayland and X11 troubleshooting paths diverge on this box.
- `claude-code` != `claude-cli` - Do not assume community Claude CLI notes apply to Anthropic Claude Code.

## Path Tags

- `~/.zshenv` -> `shell`, `zsh`, `locale`
- `~/.config/kitty/**` -> `kitty`, `terminal-theme`
- `~/REMOTE-ACCESS.md` -> `remote-access`, `ssh`, `mosh`, `remote-desktop`
```

### Synonym semantics

- Synonym edges are symmetric for retrieval.
- The left side is canonical for storage and catalog canonicalization.
- Aliases may be active tags or deprecated aliases.
- Query tokens and memory tags canonicalize before matching.
- Graph edits do not rewrite memory files.
- Each tag may appear in at most one synonym set after canonicalization.
- `link a b` merges sets deterministically and removes any distinction between `a` and `b`.

### Distinction semantics

- Distinctions are symmetric in v1.
- A distinction says "do not conflate these tags through generic/shared evidence."
- A pair cannot be both synonymous and distinguished.
- Strong evidence for one side suppresses memories tagged only with the opposite side unless the opposite tag is explicitly matched.
- A memory with both sides of a distinction is valid only with `tagConflictOk: true`; otherwise validation fails.

### Path-tag semantics

- Patterns expand `~` to `$HOME` only.
- No arbitrary environment variable expansion.
- Glob rules use Python `fnmatch.fnmatchcase`.
- Recursive `**` is allowed only as a suffix path prefix, not an arbitrary regex.
- All emitted tags canonicalize through the synonym graph before scoring.

---

## 8. Catalog

Generated file:

```text
~/.claude/projects/-home-jangman/memory/_memory_catalog.json
```

Shape:

```json
{
  "schemaVersion": 1,
  "generatedAt": "2026-05-11T12:34:56-07:00",
  "sourceFingerprint": "sha256:...",
  "memoryDir": "/home/jangman/.claude/projects/-home-jangman/memory",
  "memories": [
    {
      "id": "krdp_kcm_cert_bug",
      "file": "krdp_kcm_cert_bug.md",
      "path": "/home/jangman/.claude/projects/-home-jangman/memory/krdp_kcm_cert_bug.md",
      "name": "KRDP abandoned on this box - Sunshine+Moonlight used instead",
      "description": "Plasma 6.6.4 krdp has KCM cert-path and codec bugs; this box uses Sunshine + Moonlight instead.",
      "type": "project",
      "tags": ["kde", "plasma", "krdp", "remote-desktop"],
      "canonicalTags": ["kde", "plasma", "krdp", "remote-desktop"],
      "lastReviewed": "2026-05-09",
      "declineCount": 0
    }
  ],
  "invalidMemories": [],
  "tagToMemoryIds": {
    "krdp": ["krdp_kcm_cert_bug"]
  }
}
```

Regeneration triggers:

- edits to memory `*.md`
- edits to `_tags.md`
- edits to `_tag_links.md`
- explicit `python3 Claude-Lab/lib/memory_surface.py rebuild`

Atomicity:

- acquire `_memory_catalog.lock`
- write `_memory_catalog.json.tmp`
- fsync and `os.replace`
- release lock

If one memory is invalid, rebuild the catalog without it and list it under `invalidMemories`. Retrieval never parses or surfaces invalid entries.

---

## 9. Memory directory resolution

Resolve memory directory in this order:

1. `MEMORY_SURFACE_DIR`, if set
2. the anchored rollout corpus `~/.claude/projects/-home-jangman/memory`, if present
3. hook input `transcript_path`, deriving the project directory under `~/.claude/projects/`
4. `cwd`-derived project key only for synthetic tests or non-Claude hosts

Do not treat tool-call `cwd` as authoritative. Tool calls may run from subdirectories, added directories, or worktrees while the session memory corpus remains unchanged.

If no memory directory exists, hooks exit 0 silently.

---

## 10. MemorySearch API

`Claude-Lab/lib/memory_surface.py` exposes a stable CLI:

```sh
python3 Claude-Lab/lib/memory_surface.py validate --memory-dir ~/.claude/projects/-home-jangman/memory
python3 Claude-Lab/lib/memory_surface.py rebuild  --memory-dir ~/.claude/projects/-home-jangman/memory
python3 Claude-Lab/lib/memory_surface.py search   --memory-dir ~/.claude/projects/-home-jangman/memory --event hook-event.json
python3 Claude-Lab/lib/memory_surface.py link     --memory-dir ~/.claude/projects/-home-jangman/memory kwin plasma-compositor --reason "same retrieval domain"
python3 Claude-Lab/lib/memory_surface.py unlink   --memory-dir ~/.claude/projects/-home-jangman/memory kde-wayland kde-x11 --distinguish --reason "session stack distinction"
python3 Claude-Lab/lib/memory_surface.py add-tag  --memory-dir ~/.claude/projects/-home-jangman/memory kwin --description "KWin window manager and compositor behavior on this box."
python3 Claude-Lab/lib/memory_surface.py dismiss  --memory-dir ~/.claude/projects/-home-jangman/memory --query-id memq_... --reason "false positive"
```

Search response:

```json
{
  "schemaVersion": 1,
  "queryId": "memq_20260511_9f43a1",
  "mode": "required",
  "confidence": "high",
  "tokens": [
    {"value": "krdp", "kind": "argument", "strength": "strong"}
  ],
  "canonicalTags": ["krdp", "remote-desktop"],
  "results": [
    {
      "id": "krdp_kcm_cert_bug",
      "path": "/home/jangman/.claude/projects/-home-jangman/memory/krdp_kcm_cert_bug.md",
      "name": "KRDP abandoned on this box - Sunshine+Moonlight used instead",
      "description": "Plasma 6.6.4 krdp has KCM cert-path and codec bugs; this box uses Sunshine + Moonlight instead.",
      "tags": ["kde", "plasma", "krdp", "remote-desktop"],
      "matchedTags": ["krdp", "remote-desktop"],
      "score": 24,
      "mustRead": true
    }
  ],
  "surfaceText": "<memory-recall ...>...</memory-recall>"
}
```

Exit codes:

- `0`: command completed, even with zero results
- `2`: validation/configuration error
- `3`: graph integrity violation
- `124`: timeout from wrapper

---

## 11. Token extraction

Retrieval is triggered by `PreToolUse`.

| Tool | Extracted evidence |
|---|---|
| `Bash` | command basename, first non-flag argument, package/library names, systemd unit names, absolute paths, tilde paths |
| `Read` | target path, path-tag rules, basename tokens |
| `Edit` / `Write` / `MultiEdit` | target path, path-tag rules; memory paths route to write-context/guard |
| `WebSearch` | known tags/aliases in query only; no free-text description search |
| `WebFetch` | hostname, URL path tokens that match known tags/aliases |
| `mcp__plugin_context7_context7__*` | library/package identifier |

Generic commands do not surface by themselves:

```text
ls pwd cd cat sed awk grep rg find head tail wc jq git status git diff
```

Minimum candidate threshold:

- one strong exact active tag or alias match, or
- one configured path-tag match, or
- at least two weak matches after canonicalization

---

## 12. Ranking

Deterministic score:

```text
score =
  10 * strong_exact_tag_matches
 + 9 * path_rule_matches
 + 7 * synonym_or_alias_matches
 + 4 * path_component_matches
 + 3 * command_or_package_matches
 + 2 * memory_slug_matches
 + 1 * type_boost
 - 5 * stale_penalty
 - 2 * decline_penalty
 - 8 * distinction_conflict_penalty
```

Definitions:

- `type_boost`: `feedback` and `method` get 1, `project` gets 0.5
- `stale_penalty`: 1 if `lastReviewed` older than 180 days, else 0
- `decline_penalty`: `declineCount`, capped at 3
- `distinction_conflict_penalty`: count of wrong-side strong distinction evidence

Sort order:

1. score descending
2. strong exact matches descending
3. direct matches over synonym-only matches
4. `type` priority: `feedback`, `method`, `project`, `reference`, `todo`
5. `lastReviewed` descending
6. filename ascending

Confidence:

- `high`: score >= 10, or one strong exact tag plus one supporting signal
- `medium`: score >= 6
- `low`: below 6

High confidence creates a required obligation when required mode is enabled. Medium confidence is advisory. Low confidence is silent.

---

## 13. Hook registration

Add to `settings.global.fragment.json`.

Use exact matcher lists separately from MCP regex:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash|Read|Edit|Write|MultiEdit|WebFetch|WebSearch",
        "hooks": [
          {
            "type": "command",
            "command": "/home/jangman/.claude/hooks/memory-recall.sh",
            "timeout": 2
          },
          {
            "type": "command",
            "command": "/home/jangman/.claude/hooks/memory-obligation-guard.sh",
            "timeout": 2
          }
        ]
      },
      {
        "matcher": "mcp__plugin_context7_context7__.*",
        "hooks": [
          {
            "type": "command",
            "command": "/home/jangman/.claude/hooks/memory-recall.sh",
            "timeout": 2
          },
          {
            "type": "command",
            "command": "/home/jangman/.claude/hooks/memory-obligation-guard.sh",
            "timeout": 2
          }
        ]
      },
      {
        "matcher": "Edit|Write|MultiEdit",
        "hooks": [
          {
            "type": "command",
            "command": "/home/jangman/.claude/hooks/memory-write-context.sh",
            "timeout": 2
          },
          {
            "type": "command",
            "command": "/home/jangman/.claude/hooks/memory-write-guard.sh",
            "timeout": 5
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Read",
        "hooks": [
          {
            "type": "command",
            "command": "/home/jangman/.claude/hooks/memory-read-satisfy.sh",
            "timeout": 2
          }
        ]
      },
      {
        "matcher": "Edit|Write|MultiEdit",
        "hooks": [
          {
            "type": "command",
            "command": "/home/jangman/.claude/hooks/memory-catalog-refresh.sh",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

Ordering assumptions:

- Claude Code may run matching hooks in parallel.
- Memory hooks must be correct in isolation.
- No hook may rely on another hook running first.
- Every hook cheap-gates before spawning Python.

---

## 14. Claude Code hook behavior

### 14.1 `memory-recall.sh`

Event: `PreToolUse`

Behavior:

1. Read hook JSON from stdin.
2. Resolve memory directory.
3. Exit 0 if `.surface-disabled` exists.
4. Exit 0 for memory-dir file paths, except ledger bookkeeping.
5. Cheap-gate generic/no-signal calls.
6. Ensure catalog exists or rebuild if cheap-gate found a plausible signal.
7. Run `memory_surface.py search`.
8. If no results, exit 0.
9. Advisory/medium result: print JSON with `hookSpecificOutput.additionalContext`.
10. Required/high result: create obligation and deny the triggering tool call with a compact recall list in `permissionDecisionReason`.

Advisory JSON:

```json
{
  "suppressOutput": true,
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "additionalContext": "<memory-recall mode=\"advisory\">...</memory-recall>"
  }
}
```

Required JSON:

```json
{
  "suppressOutput": true,
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "Memory recall is required for this tool call. Read one listed memory path or dismiss with a reason, then retry. path: /home/jangman/.claude/projects/-home-jangman/memory/krdp_kcm_cert_bug.md"
  }
}
```

Rationale:

- Advisory mode cannot prevent the first matched tool execution.
- Required mode blocks before execution and is the enforceable MUST-use path.

### 14.2 `memory-obligation-guard.sh`

Event: `PreToolUse`

Behavior:

- If no open obligation, exit 0.
- If the tool is `Read` for a required memory path, allow.
- If the tool is an approved dismiss command, allow.
- Otherwise deny with the outstanding obligation and required path list.

### 14.3 `memory-read-satisfy.sh`

Event: `PostToolUse`

Behavior:

- If a `Read` path matches a required memory path, mark it satisfied.
- Reading one required memory satisfies the v1 obligation unless `requireAllRequiredReads=true`.
- If the required file disappeared, clear the obligation with a debug warning.

### 14.4 `memory-write-context.sh`

Event: `PreToolUse`

Behavior:

- If writing a memory file, inject a capped `_tags.md` excerpt via `additionalContext`.
- Never blocks.
- Does not inject for `_tags.md` or `_tag_links.md` edits.

### 14.5 `memory-write-guard.sh`

Event: `PreToolUse`

Behavior:

- Simulate `Write`, `Edit`, or `MultiEdit`.
- Validate proposed memory frontmatter and taxonomy files before write.
- Deny malformed memory writes with invalid tags, closest matches, and instructions.
- Allow bootstrap writes that create `_tags.md` and `_tag_links.md`.

### 14.6 `memory-catalog-refresh.sh`

Event: `PostToolUse`

Behavior:

- Exit 0 unless the target path is in the memory directory.
- Validate taxonomy.
- Rebuild `_memory_catalog.json`.
- If validation fails after write, return top-level `decision: "block"` and `reason`, plus optional `additionalContext`.

PostToolUse cannot undo writes. It creates immediate correction pressure and prevents silent catalog drift.

---

## 15. Obligation state

Path:

```text
${XDG_RUNTIME_DIR:-/tmp/claude-memory-surface-$UID}/recall-${session_id}.json
```

Permissions:

- parent directory mode `0700`
- atomic writes with file lock

Shape:

```json
{
  "obligations": [
    {
      "queryId": "memq_20260511_9f43a1",
      "queryHash": "sha256:...",
      "createdAt": "2026-05-11T12:34:56-07:00",
      "tool": "Bash",
      "requiredMemoryIds": ["krdp_kcm_cert_bug"],
      "requiredPaths": ["/home/jangman/.claude/projects/-home-jangman/memory/krdp_kcm_cert_bug.md"],
      "satisfiedPaths": [],
      "dismissed": false,
      "dismissReason": null
    }
  ]
}
```

Rules:

- `session_id` comes from hook input `.session_id`; fallback is `sha256(transcript_path)`.
- `queryHash` is `sha256(tool_name + "\0" + sorted(canonicalTags).join(",") + "\0" + normalized strong evidence tokens)`.
- Obligations expire after 30 minutes.
- Strict mode must never block a `Read` that would satisfy a pending obligation.
- If no session identity can be derived, required mode degrades to advisory.

Dismissals:

- allowed for false positives
- require explicit reason
- logged for taxonomy tuning

---

## 16. Surface block format

Advisory:

```xml
<memory-recall query-id="memq_..." mode="advisory" confidence="medium">
Possible project memory match for this tool call.

1. krdp_kcm_cert_bug.md
   path: /home/jangman/.claude/projects/-home-jangman/memory/krdp_kcm_cert_bug.md
   why: matched krdp, remote-desktop
   note: Plasma 6.6.4 krdp has KCM cert-path and codec bugs; this box uses Sunshine + Moonlight instead.
</memory-recall>
```

Required denial reason includes the same compact result list, but in plain text because denial reasons are shown as tool feedback.

Escaping:

- escape `&`, `<`, `>`, and attribute quotes
- truncate after escaping if needed

---

## 17. Configuration

Optional file:

```text
~/.claude/projects/-home-jangman/memory/_memory_surface_config.json
```

Defaults:

```json
{
  "schemaVersion": 1,
  "enabled": true,
  "mode": "advisory",
  "requiredMode": "strict-high-confidence",
  "maxResults": 3,
  "maxRequiredReads": 2,
  "maxDescriptionChars": 220,
  "maxBlockChars": 4000,
  "dedupeTtlSeconds": 900,
  "obligationTtlSeconds": 1800,
  "confidenceHighThreshold": 10,
  "confidenceMediumThreshold": 6,
  "requireAllRequiredReads": false,
  "debug": false
}
```

Modes:

- `disabled`
- `advisory`
- `strict-high-confidence`

Emergency kill switch:

```text
~/.claude/projects/-home-jangman/memory/.surface-disabled
```

If present, all hooks exit 0 before spawning Python.

---

## 18. Validation

`memory_surface.py validate` checks:

- `_tags.md` exists and parses
- `_tag_links.md` exists and parses
- active tag count <= 200
- tag slugs match regex
- descriptions are substantive
- deprecated tags point to active replacements
- every memory has required frontmatter
- every memory tag is active or deprecated alias
- no active tag is denylisted without policy override
- no synonym/distinction contradiction
- no tag appears in multiple synonym sets
- no path-tag rule references unknown tags
- Memory Roulette fields parse when present
- `MEMORY.md` respects router cap after Phase 3

Validation failures should be actionable one-line diagnostics:

```text
memory-write-guard: krdp_kcm_cert_bug.md has unknown tag `rdp`; use `remote-desktop` or add `rdp` to _tags.md first.
```

---

## 19. Failure modes

| Failure | Behavior |
|---|---|
| memory directory missing | hooks exit 0 |
| `.surface-disabled` exists | hooks exit 0 before Python |
| `_tags.md` missing during bootstrap | allow taxonomy creation, no recall |
| `_tags.md` missing after bootstrap | retrieval fails open, writes fail closed |
| malformed graph | retrieval fails open, taxonomy writes fail closed |
| graph synonym/distinction conflict | validation fails; no new catalog |
| catalog missing | rebuild after cheap-gate plausible signal |
| catalog parse error | no recall, debug log only |
| invalid individual memory | omit and list in `invalidMemories` |
| hook timeout | no recall, debug log only |
| false positive required match | user/model may dismiss with reason; log for tuning |
| false negative | add tag, path-tag, synonym, or manual search; no prompt-substring fallback |
| stale memory | penalize but do not hide; model still verifies time-sensitive facts |
| obligation deadlock | TTL expiry, dismiss command, and read-loop exemption |
| concurrent rebuild | lock and atomic replace |

General rule:

- retrieval errors fail open
- taxonomy writes fail closed
- obligations fail closed only when strict mode has successfully created state

---

## 20. Rollout

### Phase 0 - Data preparation

- Add `_tags.md` and `_tag_links.md`.
- Add `tags: [...]` to existing memories.
- Build `_memory_catalog.json`.
- Validate Memory Roulette still preserves unknown fields.
- Leave `MEMORY.md` unchanged temporarily.

### Phase 1 - Write-time validation

- Add `memory-write-context.sh`.
- Add `memory-write-guard.sh`.
- Add `memory-catalog-refresh.sh`.
- Register validation hooks.
- Unknown tags are denied before memory writes.

### Phase 2 - Search dry run

- Implement `memory_surface.py search`.
- Add token extraction and ranking.
- Run synthetic hook payloads.
- Log matches only; no surfacing or blocking.

### Phase 3 - Advisory surfacing and `MEMORY.md` cutover

- Add `memory-recall.sh` advisory output.
- Convert `MEMORY.md` to capped router.
- Replace old `CLAUDE.md.fragment` memory instruction.
- Observe false positives and false negatives.

### Phase 4 - Required surfacing

- Enable high-confidence required mode.
- Add `memory-obligation-guard.sh`.
- Add `memory-read-satisfy.sh`.
- Add dismiss flow and obligation TTL.
- Verify deny -> Read -> retry loop.

### Phase 5 - Optional manual MemorySearch

- Add a small skill or command note for manual searches.
- Keep manual search advisory by default.
- Use required mode only for hook-triggered high-confidence calls.

---

## 21. Tests

Unit tests:

- frontmatter parser
- one-line tag parser
- `_tags.md` parser
- `_tag_links.md` parser
- synonym canonicalization
- overlapping synonym rejection
- synonym/distinction conflict rejection
- distinction wrong-side suppression
- path-tag matching
- Bash token extraction
- WebSearch known-tag extraction
- ranking and caps
- XML escaping
- obligation create/satisfy/dismiss/expire
- atomic catalog write

Integration tests:

- `Bash systemctl --user status krdp.service` returns KRDP memory
- `Read ~/.zshenv` returns zsh/locale/mosh memory
- `git status --short` returns no recall
- `NotebookRead` does not fire because matchers are separated
- unknown memory tag is denied with closest matches
- required flow: deny -> Read required memory -> retry allowed
- Stop/final-answer guard, if implemented, blocks unsatisfied obligation
- missing memory dir fails open
- `.surface-disabled` fails open
- `install.sh --dry-run` shows hook registration and does not alter permission modes

Performance tests:

- 200 active tags
- 150 memory files
- 500 semantic links
- warm no-match target under 50 ms
- warm match target under 150 ms
- output never exceeds caps

Regression tests:

- user prompt text alone cannot trigger recall
- memory descriptions are never free-text matched against the prompt
- memory bodies are never inlined by recall hook
- broad tags like `config`, `linux`, and `tool` cannot become active without explicit policy override
- Memory Roulette keep/refresh/later/toss does not lose `tags`

---

## 22. Acceptance criteria

V1 is complete when:

- every existing memory has valid `tags`
- `_tags.md`, `_tag_links.md`, and `_memory_catalog.json` exist
- `MEMORY.md` is a capped router after advisory surfacing ships
- unknown tags are rejected before memory writes
- synonym links retrieve through canonical tags
- distinction links suppress known false-positive conflation
- advisory recall surfaces at most 3 descriptions
- required recall blocks high-confidence tool calls until read or dismissal
- reading a required memory clears the obligation
- generic tool calls stay silent
- no memory body is auto-loaded
- tests cover validation, extraction, ranking, obligations, hook JSON, and caps

---

## 23. Build order checklist

1. Add `Claude-Lab/lib/memory_surface.py` with `validate`, `rebuild`, `search`, `link`, `unlink`, `add-tag`, and obligation commands.
2. Add `_tags.md` and `_tag_links.md`.
3. Tag current memory files.
4. Generate `_memory_catalog.json`.
5. Add unit tests.
6. Add write-context, write-guard, and catalog-refresh hooks.
7. Register validation hooks and run installer dry-run.
8. Add dry-run search fixtures.
9. Add advisory recall hook.
10. Convert `MEMORY.md` to router and replace CLAUDE.md memory instruction.
11. Enable advisory surfacing.
12. Tune with real sessions.
13. Add obligation guard and read-satisfy hook.
14. Enable strict-high-confidence required mode.
15. Run full integration and performance tests.

---

## 24. Design stance

This is a library catalog, not a second brain.

The user curates subject headings and semantic edges. Hooks route concrete tool-call evidence through those headings. Claude sees a bounded checkout slip. If the slip is high confidence, Claude must read or dismiss it before proceeding. The corpus can grow; the prompt surface cannot.
