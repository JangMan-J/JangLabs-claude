# Memory surfacing implementation specification

<!-- handoff-scope: claude -->

**Status:** Implementation spec v1, reviewed by independent Claude and Codex agents.  
**Created:** 2026-05-11.  
**Source overview:** `Claude-Lab/handoffs/2026-05-10-memory-system-overhaul.md`.  
**Target system:** `~/.claude/projects/-home-jangman/memory/` plus the `Claude-Lab` hook harness.  
**Primary goal:** Make the memory corpus compound across sessions while preserving a hard-bounded prompt surface.

This document turns the 2026-05-10 rough draft into a buildable specification. It intentionally resolves the rough draft's open questions where an implementation needs a concrete answer.

---

## 1. Review conclusions

The rough draft's core architecture is sound:

- Retrieval must move from always-loaded prose skim to tool-call-triggered recall.
- Memory bodies must never be auto-loaded.
- The unbounded artifact is the memory catalog and tag graph; the bounded artifact is the recall surface.
- Claude cannot be trusted to maintain cross-session tag discipline without write-time validation.
- The user must remain the taxonomy owner for semantic merges and distinctions.

The implementation needs these corrections or clarifications:

1. **Use Claude Code `additionalContext` for recall injection.** Current Claude Code hook docs support `hookSpecificOutput.additionalContext` for `PreToolUse`. Plain stdout from `PreToolUse` is not visible to Claude unless returned as structured JSON. The hook must exit 0 and print only JSON when injecting context.
2. **Keep corpus data beside the memory corpus.** The hook code belongs in `Claude-Lab`; the vocabulary, graph, path rules, and generated catalog belong in the active project's `memory/` directory. This keeps taxonomy state scoped to the corpus it indexes.
3. **Resolve the memory directory from session identity, not ambient shell state.** The rollout target is the anchored corpus `~/.claude/projects/-home-jangman/memory/`. Generic installs may derive a project memory directory from the hook `transcript_path`, but `cwd` is only a fallback. A tool call can run from a subdirectory or added directory without changing which memory corpus owns the session.
4. **Make strict enforcement configurable, and be honest about advisory limits.** A hook can inject recall context reliably. It cannot prove arbitrary model cognition in advisory mode. For Claude Code, strict mode can deny a high-confidence tool call until a matching memory has been read; advisory mode ships first to avoid workflow thrash, but this explicitly defers the strongest "MUST-use" enforcement until strict mode is enabled.
5. **Do not leave `MEMORY.md` as a growing always-loaded index.** Once recall ships, `MEMORY.md` becomes a capped router and tag-vocabulary surface, not a list of every memory. Otherwise the index-skim failure mode remains in parallel with the new system.
6. **Do not revive prompt-substring retrieval.** The reverted `memory-relevance-injector.sh` matched user prompts and inlined bodies. This spec only uses tool-call payloads and surfaces summaries.

Reference docs used for hook semantics:

- Claude Code hooks reference: `https://code.claude.com/docs/en/hooks`

---

## 2. Product contract

### 2.1 One-sentence contract

When an AI agent is about to use a tool, the memory surfacing system extracts concrete tool-call signals, resolves them through a user-curated tag graph, and returns at most a few relevant memory summaries that the agent must consider before continuing on that topic.

### 2.2 User-facing behavior

When Claude runs a tool call that strongly matches memory tags, Claude receives a compact block like:

```xml
<memory-recall source="PreToolUse:Bash" queryId="memq_20260511_9f83" required="true">
Memory recall found project-specific notes related to this tool call.

1. krdp_kcm_cert_bug.md
   KRDP abandoned on this box; use Sunshine + Moonlight unless both upstream bugs are fixed.
   Tags: krdp, remote-access, plasma, sunshine

2. remote_access_doc.md
   ~/REMOTE-ACCESS.md is the canonical remote-access reference for SSH, mosh, KRDP, Sunshine, Tailscale, and firewall layout.
   Tags: remote-access, tailscale, firewall
</memory-recall>
```

The block is small. It contains names, descriptions, tags, and file paths only. Claude reads a full memory body only when the summary is action-changing or needed to answer safely.

### 2.3 Non-negotiable caps

These caps are hard requirements:

| Surface | Cap |
|---|---:|
| Results per recall event | 3 memories |
| Description characters per result | 220 hard cap, 150 target |
| Full bodies auto-loaded by hook | 0 |
| Recall block total size | 2500 chars target, 4000 chars hard cap |
| Recall events per identical query per session | dedupe by `queryHash` for 900s by default |
| Tags per memory | 8 hard cap, 3-5 target |
| Tag token length | 2-40 chars |
| Tag vocabulary injected during memory writes | 200 lines hard cap |
| Always-loaded `MEMORY.md` after rollout | 20 lines target, 40 lines hard cap |

If a cap would be exceeded, truncate or drop lower-ranked results. Never spill additional memory bodies into context.

---

## 3. Scope

### 3.1 In scope

- Add `tags:` frontmatter to each memory file.
- Add a canonical tag vocabulary.
- Add a synonym/distinction graph for semantic tag linking and unlinking.
- Add path and command rules that map concrete tool-call payloads to tags.
- Add a generated memory catalog cache.
- Add write-time validation for memory frontmatter and vocabulary changes.
- Add write-time tag-vocabulary surfacing so an invalid memory write returns enough bounded context to retry with canonical tags.
- Add `PreToolUse` recall injection for selected tool calls.
- Add an implementation-neutral `MemorySearch` request/response contract.
- Convert `MEMORY.md` from a growing always-loaded memory index into a small router/tag-vocabulary surface once recall is active.
- Add tests using synthetic hook payloads.

### 3.2 Out of scope

- Embedding search.
- Prompt-substring matching.
- Auto-loading memory bodies.
- Automatic vocabulary expansion.
- Automatic semantic graph curation.
- Global memory across unrelated projects.
- A new MCP server in the first implementation.
- Machine-learning ranking.

### 3.3 Optional later scope

- A Claude-invoked `MemorySearch` tool for long-tail misses.
- A small CLI for user-friendly graph curation.
- Strict required-recall mode after advisory mode proves useful.
- Per-project installed skill that teaches model behavior around recall blocks.

---

## 4. Architecture

### 4.1 Components

| Component | Path | Ownership | Purpose |
|---|---|---|---|
| Memory router | `~/.claude/projects/<project-key>/memory/MEMORY.md` | User/Claude | Always-loaded capped router; not the full memory index after rollout |
| Memory files | `~/.claude/projects/<project-key>/memory/*.md` | User/Claude | Source-of-truth memory bodies and frontmatter |
| Tag vocabulary | `~/.claude/projects/<project-key>/memory/_tags.json` | User-curated | Canonical tag set and descriptions |
| Tag graph | `~/.claude/projects/<project-key>/memory/_tag_graph.json` | User-curated | Synonyms and distinctions |
| Path rules | `~/.claude/projects/<project-key>/memory/_path_tags.json` | User-curated with Claude help | Maps paths, commands, hosts, and package names to tags |
| Catalog cache | `~/.claude/projects/<project-key>/memory/_memory_catalog.json` | Generated | Parsed memories, tag index, validation state |
| Recall hook | `Claude-Lab/hooks/memory-recall.sh` | Claude-Lab | `PreToolUse` hook wrapper |
| Write guard | `Claude-Lab/hooks/memory-write-guard.sh` | Claude-Lab | `PreToolUse` validation for memory writes |
| Catalog refresh | `Claude-Lab/hooks/memory-catalog-refresh.sh` | Claude-Lab | `PostToolUse` validation and cache rebuild |
| Engine | `Claude-Lab/lib/memory_surface.py` | Claude-Lab | Parsing, validation, graph resolution, ranking |

### 4.2 Data locality decision

The taxonomy data lives in the memory directory, not in `Claude-Lab/data/`.

Reason:

- Tags and graph edges describe a specific corpus.
- The same hook code should work for any project memory directory.
- User curation should travel with the memories, not with one machine-level harness release.
- Generated cache invalidation is simpler when all corpus data shares one directory.

`Claude-Lab/data/` may later hold templates or seed examples, but not live taxonomy state.

### 4.3 Project memory directory resolution

For this rollout, the default memory corpus is the overview's anchored corpus:

```text
~/.claude/projects/-home-jangman/memory
```

The engine must still be generic enough to support other Claude project corpora. Resolve the memory directory in this order:

1. `MEMORY_SURFACE_DIR`, if set. This is the explicit override and is the supported way to pin a global box-level memory corpus.
2. `~/.claude/projects/-home-jangman/memory`, for this install, if it exists.
3. The hook input `transcript_path`, if present. The project key is the directory under `~/.claude/projects/` that contains the transcript JSONL file.
4. `cwd`-derived project key only as a last fallback for synthetic tests and non-Claude hosts.

Do not treat a tool call's current working directory as authoritative. Claude can run tools from subdirectories, added directories, or a repo worktree while the session still belongs to a different Claude project memory corpus.

If no memory directory exists after this resolution, all memory hooks exit 0 silently.

### 4.4 Hook registration

Add these hooks to `Claude-Lab/settings.global.fragment.json`:

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
          }
        ]
      },
      {
        "matcher": "mcp__.*",
        "hooks": [
          {
            "type": "command",
            "command": "/home/jangman/.claude/hooks/memory-recall.sh",
            "timeout": 2
          }
        ]
      },
      {
        "matcher": "Edit|Write|MultiEdit",
        "hooks": [
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

Installer behavior remains unchanged: symlink all `hooks/*.sh` into `~/.claude/hooks/`, then merge settings idempotently.

Matcher requirement:

- Keep exact tool-name matchers separate from `mcp__.*`. In Claude Code, matchers containing only letters, digits, `_`, and `|` are exact tool-name lists. Adding `.*` turns the matcher into a regular expression, so `Read` could accidentally match future tool names such as `NotebookRead` if combined with regex text.

Hook ordering requirement:

- Claude Code runs all matching hooks in parallel and deduplicates identical handlers by command string.
- No memory hook may rely on another hook running first.
- Each hook must be correct in isolation, cheap-gate before invoking Python, and tolerate a tool call that another hook will also deny.

### 4.5 Always-loaded `MEMORY.md`

`MEMORY.md` is still loaded by Claude Code memory behavior, so it cannot remain a line-per-memory index once tool-call recall ships. The success condition from the overview depends on this file staying compact even when the corpus grows.

V1 transition:

1. Phase 0 may leave the existing `MEMORY.md` index in place while tags are seeded.
2. Phase 3 must replace the growing index with a capped router that explains the recall hook, points to `_tags.json`, and includes either a compact tag list or a pointer to read `_tags.json` before memory writes.
3. After Phase 3, `MEMORY.md` must not list every memory file. The write guard warns above 20 lines and denies above 40 lines unless `MEMORY_SURFACE_ALLOW_LONG_INDEX=1` is set for a manual migration.

The router may include a generated tag excerpt, but it must obey the same 200-line maximum used for write-time vocabulary surfacing. Memory bodies and line-per-memory summaries belong behind the catalog, not in the always-loaded prompt.

---

## 5. Frontmatter contract

### 5.1 Required fields

Each memory file except `MEMORY.md` and `_*.md` must have YAML-like frontmatter:

```yaml
---
name: KRDP abandoned on this box - Sunshine+Moonlight used instead
description: Plasma 6.6.4 krdp has two unrelated bugs; use Sunshine + Moonlight for Plasma streaming unless both upstream bugs are fixed.
type: project
tags: [krdp, plasma, remote-access, sunshine, moonlight]
lastReviewed: 2026-05-09
declineCount: 0
---
```

Required:

- `name`
- `description`
- `type`
- `tags`

Optional but preserved:

- `originSessionId`
- `lastReviewed`
- `declineCount`
- `nextEligible`
- any unknown key already supported by `_review_game.py`

### 5.2 Tags field syntax

Use one-line flow-list syntax:

```yaml
tags: [kde, plasma, kwin-wayland]
```

Do not use multi-line YAML for tags in v1. The existing Memory Roulette parser is line-oriented and should remain simple.

### 5.3 Tag token rules

A tag token must:

- match `^[a-z0-9][a-z0-9-]{1,39}$`
- be lowercase
- use hyphens, not underscores
- avoid version numbers unless the version is the point of the memory
- exist in `_tags.json`
- not appear in the denylist

Examples:

| Good | Bad | Why |
|---|---|---|
| `kde-wayland` | `wayland` | `wayland` may be too broad unless vocabulary defines it narrowly |
| `remote-access` | `config` | generic |
| `claude-code` | `ClaudeCode` | wrong case/style |
| `nvidia-wayland` | `nvidia_6.6` | underscore and version noise |

### 5.4 Type values

Allowed `type` values:

- `project`
- `feedback`
- `method`
- `reference`
- `todo`

Existing memories using other values should be grandfathered but flagged by `memory_surface.py validate`.

---

## 6. Taxonomy files

JSON is the v1 format. It is more verbose than Markdown, but it is dependency-light, parseable with `jq` and Python stdlib, and compatible with the existing installer requirement for `jq`.

All JSON files must be stable-formatted with `jq -S .`.

### 6.1 `_tags.json`

Path:

```text
~/.claude/projects/<project-key>/memory/_tags.json
```

Schema:

```json
{
  "schemaVersion": 1,
  "policy": {
    "maxTagsPerMemory": 8,
    "targetTagsPerMemory": "3-5",
    "maxSurfaceResults": 3,
    "maxDescriptionChars": 220,
    "antiGenericDescriptionMinWords": 6
  },
  "denylist": [
    "bug",
    "config",
    "file",
    "linux",
    "memory",
    "setup",
    "tool"
  ],
  "tags": {
    "krdp": {
      "description": "KDE RDP server and kcm_krdpserver behavior on this box.",
      "kind": "software",
      "status": "active"
    },
    "remote-access": {
      "description": "SSH, mosh, tmux, Tailscale, firewall, remote desktop, and phone access setup.",
      "kind": "domain",
      "status": "active"
    }
  }
}
```

Field rules:

- `schemaVersion` must be `1`.
- `policy` values are read by validators and recall hook.
- `denylist` is enforced for new tags.
- `tags` keys are canonical tag tokens.
- Each tag `description` must be one sentence or fragment, 6-25 words.
- `kind` is one of `software`, `domain`, `subsystem`, `hardware`, `workflow`, `path`, `project`, `other`.
- `status` is `active` or `deprecated`.
- A deprecated tag must include `replacement` unless it is intentionally dead.

Deprecated example:

```json
{
  "description": "Old tag retained only for historical frontmatter compatibility.",
  "kind": "software",
  "status": "deprecated",
  "replacement": "claude-code"
}
```

### 6.2 `_tag_graph.json`

Path:

```text
~/.claude/projects/<project-key>/memory/_tag_graph.json
```

Schema:

```json
{
  "schemaVersion": 1,
  "synonyms": [
    {
      "canonical": "kwin",
      "members": ["plasma-compositor"],
      "reason": "For this corpus, KWin compositor memories should be retrieved by either term.",
      "created": "2026-05-11"
    }
  ],
  "distinctions": [
    {
      "left": "kde-wayland",
      "right": "kde-x11",
      "mode": "symmetric",
      "reason": "Wayland and X11 troubleshooting paths diverge on this box.",
      "leftEvidence": ["wayland", "kwin_wayland", "xdg-desktop-portal-kde"],
      "rightEvidence": ["x11", "xcb", "xorg"]
    }
  ]
}
```

Synonym rules:

- `canonical` must exist in `_tags.json`.
- `members` must exist in `_tags.json`.
- Synonym edges are symmetric for retrieval.
- Canonicalization maps every member to the canonical tag.
- Synonym edits do not rewrite memory files.
- Each tag may appear in at most one synonym set, either as `canonical` or as a member.
- `memory_surface.py link` must merge existing sets into a single deterministic set instead of writing overlapping entries.

Distinction rules:

- Distinctions are symmetric in v1.
- A distinction says "do not expand or conflate these tags."
- Distinctions do not prevent a memory from surfacing if the exact tag is present.
- Evidence arrays are optional token hints used to classify ambiguous tool payloads.

Conflict rules:

- A tag pair cannot be both synonymous and distinguished.
- A synonym set cannot contain two tags that are distinguished anywhere in the graph.
- Overlapping synonym entries are invalid after CLI normalization.
- Validation fails closed on graph conflicts.

### 6.3 `_path_tags.json`

Path:

```text
~/.claude/projects/<project-key>/memory/_path_tags.json
```

Schema:

```json
{
  "schemaVersion": 1,
  "rules": [
    {
      "match": "exact",
      "pattern": "~/.zshenv",
      "tags": ["zsh", "locale", "mosh"],
      "strength": "strong",
      "reason": "Blink/mosh locale failures were fixed in ~/.zshenv."
    },
    {
      "match": "prefix",
      "pattern": "~/.config/kitty/",
      "tags": ["kitty", "terminal-theme"],
      "strength": "strong"
    },
    {
      "match": "command",
      "pattern": "krdpserver",
      "tags": ["krdp", "remote-access"],
      "strength": "strong"
    },
    {
      "match": "host",
      "pattern": "docs.anthropic.com",
      "tags": ["claude-code"],
      "strength": "weak"
    }
  ]
}
```

Supported `match` values:

- `exact`: exact path after `~` and env expansion
- `prefix`: path prefix after expansion
- `glob`: shell-style glob, never regex
- `command`: command basename extracted from a Bash payload
- `host`: hostname extracted from WebFetch URL
- `package`: package/library name extracted from MCP or web payloads
- `token`: exact normalized token

Supported `strength` values:

- `strong`: enough to surface one high-scoring memory by itself
- `weak`: only useful with another weak signal or exact memory tag hit

All rule tags must exist in `_tags.json`.

### 6.4 `_memory_catalog.json`

Path:

```text
~/.claude/projects/<project-key>/memory/_memory_catalog.json
```

This file is generated. Humans do not edit it.

Schema:

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
      "description": "Plasma 6.6.4 krdp has two unrelated bugs; use Sunshine + Moonlight for Plasma streaming unless both upstream bugs are fixed.",
      "type": "project",
      "tags": ["krdp", "plasma", "remote-access", "sunshine", "moonlight"],
      "canonicalTags": ["krdp", "plasma", "remote-access", "sunshine", "moonlight"],
      "lastReviewed": "2026-05-09",
      "declineCount": 0,
      "nextEligible": null
    }
  ],
  "invalidMemories": [
    {
      "file": "broken_memory.md",
      "path": "/home/jangman/.claude/projects/-home-jangman/memory/broken_memory.md",
      "error": "unknown tag: kde-config"
    }
  ],
  "tagToMemoryIds": {
    "krdp": ["krdp_kcm_cert_bug"],
    "remote-access": ["krdp_kcm_cert_bug", "remote_access_doc"]
  }
}
```

Regeneration triggers:

- Any write to `memory/*.md`
- Any write to `_tags.json`
- Any write to `_tag_graph.json`
- Any write to `_path_tags.json`
- Explicit `memory_surface.py rebuild`

PreToolUse recall may rebuild the catalog if it is missing or stale, but only after cheap gating finds a plausible retrieval signal. If rebuild fully fails or times out, retrieval fails open and the tool call proceeds. If only some memory files fail validation, rebuild a catalog that omits those files and records them in `invalidMemories`; recall must never parse or surface an invalid memory entry.

---

## 7. Semantic link/unlink model

### 7.1 Definitions

**Link** means adding a synonym edge.

Example:

```text
link kwin plasma-compositor
```

Effect:

- Queries for `kwin` retrieve memories tagged `plasma-compositor`.
- Queries for `plasma-compositor` retrieve memories tagged `kwin`.
- Catalog canonicalization emits `kwin` for both.
- Memory files are not rewritten.

**Unlink** means removing a synonym edge. It may optionally add a distinction.

Example:

```text
unlink claude-code claude-cli --distinguish
```

Effect:

- The tags no longer canonicalize together.
- If `--distinguish` is used, the graph records that the pair must not be conflated.
- Existing memories keep their tags.

### 7.2 Why there is no generic `related` edge in v1

The rough draft's purpose is to resist erosion. A fuzzy `related_to` edge is tempting but creates a second uncontrolled expansion surface. V1 has only:

- `synonym`: same retrieval identity
- `distinction`: explicit non-identity

If recall has too many false negatives after real use, add a `related` edge later with a lower weight and a separate cap. Do not include it in v1.

### 7.3 CLI contract for curation

The implementation should expose a small CLI through `Claude-Lab/lib/memory_surface.py`:

```sh
python3 Claude-Lab/lib/memory_surface.py validate --memory-dir ~/.claude/projects/-home-jangman/memory
python3 Claude-Lab/lib/memory_surface.py rebuild  --memory-dir ~/.claude/projects/-home-jangman/memory
python3 Claude-Lab/lib/memory_surface.py search   --memory-dir ~/.claude/projects/-home-jangman/memory --event hook-event.json
python3 Claude-Lab/lib/memory_surface.py add-tag --memory-dir ~/.claude/projects/-home-jangman/memory kwin --kind software --description "KWin compositor and window-manager behavior relevant to this box."
python3 Claude-Lab/lib/memory_surface.py deprecate-tag --memory-dir ~/.claude/projects/-home-jangman/memory old-tag --replacement new-tag --reason "..."
python3 Claude-Lab/lib/memory_surface.py link     --memory-dir ~/.claude/projects/-home-jangman/memory kwin plasma-compositor --reason "..."
python3 Claude-Lab/lib/memory_surface.py unlink   --memory-dir ~/.claude/projects/-home-jangman/memory claude-code claude-cli --distinguish --reason "..."
python3 Claude-Lab/lib/memory_surface.py remove-distinction --memory-dir ~/.claude/projects/-home-jangman/memory claude-code claude-cli --reason "..."
```

The graph curation commands edit only `_tag_graph.json`. They must:

- refuse unknown tags
- refuse graph conflicts
- preserve existing JSON formatting with sorted keys
- run validation after edit
- not rewrite memory files

`link` must merge existing synonym sets deterministically. The command keeps the first existing canonical tag when one side is already canonical; otherwise it uses the first command argument as canonical. It must remove any distinction between the linked tags.

`unlink` removes only the named pair from a synonym set. If a set has more than two members, the remaining members stay linked under the existing canonical unless the canonical was removed; in that case the lexicographically first remaining tag becomes canonical. `--distinguish` adds a symmetric distinction after unlinking.

The tag vocabulary commands edit only `_tags.json`. They must preserve sorted formatting, validate descriptions, and refuse to remove active tags that are still referenced by memory files, path rules, or graph edges.

---

## 8. MemorySearch API

This is the model-agnostic contract. Claude Code hooks are one binding of this contract.

### 8.1 Request

```json
{
  "schemaVersion": 1,
  "trigger": {
    "source": "tool_call",
    "hookEventName": "PreToolUse",
    "toolName": "Bash",
    "toolUseId": "toolu_...",
    "toolInput": {
      "command": "systemctl --user status krdp.service"
    }
  },
  "scope": {
    "cwd": "/home/jangman",
    "memoryDir": "/home/jangman/.claude/projects/-home-jangman/memory",
    "sessionId": "..."
  },
  "limits": {
    "maxResults": 3,
    "maxDescriptionChars": 220,
    "maxBlockChars": 4000
  },
  "mode": "advisory"
}
```

### 8.2 Response

```json
{
  "schemaVersion": 1,
  "queryId": "memq_20260511_9f83",
  "required": true,
  "confidence": "high",
  "tokens": [
    {"value": "systemctl", "kind": "command", "strength": "weak"},
    {"value": "krdp", "kind": "argument", "strength": "strong"}
  ],
  "tags": ["krdp", "remote-access", "systemd"],
  "results": [
    {
      "id": "krdp_kcm_cert_bug",
      "file": "krdp_kcm_cert_bug.md",
      "path": "/home/jangman/.claude/projects/-home-jangman/memory/krdp_kcm_cert_bug.md",
      "name": "KRDP abandoned on this box - Sunshine+Moonlight used instead",
      "description": "Plasma 6.6.4 krdp has two unrelated bugs; use Sunshine + Moonlight for Plasma streaming unless both upstream bugs are fixed.",
      "tags": ["krdp", "plasma", "remote-access", "sunshine", "moonlight"],
      "score": 8.2,
      "why": ["matched strong tag krdp", "matched tag remote-access"]
    }
  ],
  "surfaceText": "<memory-recall ...>...</memory-recall>"
}
```

### 8.3 Required semantics

For any host implementing this API:

- If `required` is `true`, the host must expose `surfaceText` to the model before the model continues on the same topic.
- The model must treat listed memories as retrieved context.
- In advisory mode, the model must explicitly account for a required recall block: read at least one listed memory when it may change the action, or state briefly why the summaries are sufficient.
- In strict mode, the host enforces the read step by denying matching high-confidence tool calls until at least one required memory path has been read.
- The host must not auto-load bodies unless the user explicitly opts into a more aggressive mode.

For Claude Code v1, "must expose" is implemented by `additionalContext`.

---

## 9. Tool-call token extraction

### 9.1 Normalization

All extracted tokens are normalized before tag resolution:

- lowercase
- strip surrounding quotes
- replace `_`, `.`, and spaces with `-` for candidate tag matching
- keep original token for evidence
- split paths into meaningful components
- strip common version suffixes unless the token is clearly a version-specific tag
- ignore tokens shorter than 2 chars

### 9.2 Stop tokens

Global stop tokens include:

```text
the and for with from into onto this that these those file files config setup tool tools
run get set show list status open edit write read search find grep rg cat head tail sed awk jq
```

Stop tokens do not become query tags by themselves.

### 9.3 Bash extraction

Input field:

```jq
.tool_input.command
```

Extraction:

1. Split command into segments at `;`, `&&`, `||`, and `|` without executing or expanding anything.
2. For each segment, extract:
   - command basename
   - first non-flag argument
   - absolute paths
   - tilde paths
   - unit names like `krdp.service`
   - package names after `pacman`, `yay`, `pip`, `uv`, `npm`, `cargo`
3. Apply `_path_tags.json` `command`, `exact`, `prefix`, `glob`, `package`, and `token` rules.
4. Ignore generic commands unless their arguments match strong rules.

Generic Bash commands that do not surface by themselves:

```text
ls pwd cd rg grep find cat sed awk head tail wc jq git stat file which type command
```

Examples:

| Command | Extracted strong tags |
|---|---|
| `systemctl --user status krdp.service` | `krdp`, `remote-access`, `systemd` |
| `sed -n '1,80p' ~/.zshenv` | `zsh`, `locale`, `mosh` |
| `rg krdp ~/.config` | `krdp` if token exists; path tags if matched |
| `git status --short` | none |

### 9.4 Read/Edit/Write/MultiEdit extraction

Input fields:

```jq
.tool_input.file_path // .tool_input.path
```

Extraction:

- absolute path
- tilde-normalized path
- basename without extension
- parent directory components
- `_path_tags.json` path rules

Memory-specific behavior:

- If the path is under `memory/`, do not run normal recall.
- Instead, `memory-write-guard.sh` validates memory taxonomy writes.
- Reading a surfaced memory path marks the pending strict-mode recall as satisfied.

### 9.5 WebSearch extraction

Input field:

```jq
.tool_input.query
```

Extraction:

- quoted phrases
- capitalized product/project names
- package/library names
- stopword-filtered tokens
- version numbers retained as weak evidence only

WebSearch signals are weak unless they exactly match a vocabulary tag or path rule.

### 9.6 WebFetch extraction

Input fields:

```jq
.tool_input.url
.tool_input.prompt
```

Extraction:

- hostname
- URL path components
- prompt tokens
- `_path_tags.json` host rules

### 9.7 MCP extraction

Tool names:

```text
mcp__<server>__<tool>
```

Extraction:

- server name
- tool name components
- common argument fields:
  - `query`
  - `url`
  - `path`
  - `file_path`
  - `library`
  - `package`
  - `repo`
  - `owner`
  - `name`

Context7-style tools should extract the requested package/library as a package token.

---

## 10. Graph resolution

### 10.1 Resolution pipeline

For each token:

1. Normalize token.
2. Match direct vocabulary tag.
3. Apply `_path_tags.json` rules.
4. Canonicalize through synonym graph.
5. Apply distinction evidence.
6. Emit resolved tag candidates with strength and provenance.

All tags emitted by path, command, host, package, or token rules are canonicalized through the synonym graph before scoring.

### 10.2 Synonym canonicalization

Build a union-find structure from `synonyms`.

For each synonym set:

- canonical tag is the set representative
- every member maps to canonical
- catalog `canonicalTags` includes canonical representatives

The original tag remains visible in `tags` for auditability.

### 10.3 Distinction handling

Distinctions prevent accidental expansion. They do not hide exact matches.

Example:

- Query evidence contains `x11`.
- Graph distinguishes `kde-wayland` from `kde-x11`.
- Memories tagged `kde-wayland` lose any score gained from generic `kde` or compositor-adjacent evidence unless `kde-wayland` was also explicitly matched.

In v1, distinction handling has a hard guardrail plus a score penalty:

- If strong evidence identifies one side of a distinction, memories tagged only with the opposite side cannot gain score from shared or generic evidence such as `kde`, `plasma`, `config`, or compositor-adjacent tokens.
- A wrong-side memory may still surface if the tool payload exactly matches one of its own tags or an explicit path rule names one of its tags.
- If a memory is intentionally tagged with both sides of a distinction, validation warns and the memory is exempt from the penalty for that pair.

After the hard guardrail, scoring is simple:

- exact distinguished-side evidence: `+2`
- opposite-side evidence: `-3`
- exact tag match: cannot be reduced below `+1`

This keeps exact user tags authoritative while preventing training-prior conflation.

---

## 11. Ranking

### 11.1 Candidate selection

A memory is a candidate if:

- any canonical memory tag intersects resolved strong tags, or
- at least two weak resolved tags intersect, or
- a path rule directly names one of its tags, or
- strict mode has a pending recall for that memory.

### 11.2 Score formula

Use a deterministic score:

```text
score =
  4.0 * strong_exact_tag_matches
+ 2.5 * path_rule_matches
+ 2.0 * command_or_package_rule_matches
+ 1.0 * weak_tag_matches
+ 0.5 * type_boost
+ 0.3 * freshness_boost
- 0.4 * decline_penalty
- 3.0 * distinction_conflict_penalty
```

Definitions:

- `type_boost`: `0.5` for `feedback` or `method`, `0.2` for `project`, `0` otherwise.
- `freshness_boost`: `0.3` if reviewed in the last 90 days, `0.1` if reviewed in the last 180 days, `0` otherwise.
- `decline_penalty`: `declineCount`, capped at 5.
- `distinction_conflict_penalty`: count of opposite-side distinction evidence.

### 11.3 Result ordering

Sort by:

1. score descending
2. number of strong matches descending
3. `type` priority: `feedback`, `method`, `project`, `reference`, `todo`
4. `lastReviewed` descending
5. filename ascending

Return the first `maxSurfaceResults`.

### 11.4 Required vs advisory confidence

Set response `confidence`:

- `high`: score >= configured high threshold, default `5`, or at least one strong exact tag plus one supporting signal
- `medium`: score >= configured medium threshold, default `3`
- `low`: score below the configured medium threshold

Set `required`:

- `true` for high confidence
- `false` for medium confidence in advisory mode
- no surface for low confidence

Strict mode may deny high-confidence tool calls until recall is satisfied.

---

## 12. Claude Code hook behavior

### 12.1 `memory-recall.sh`

Event:

```text
PreToolUse
```

Matchers:

```text
Bash|Read|Edit|Write|MultiEdit|WebFetch|WebSearch
mcp__.*
```

Behavior:

1. Read hook JSON from stdin.
2. Resolve memory directory using the order in section 4.3.
3. Cheap-gate:
   - exit 0 if no memory dir
   - exit 0 for generic tool payloads with no strong token
   - exit 0 for `Read` / `Edit` / `Write` / `MultiEdit` paths under `memoryDir/`, except strict-mode ledger satisfaction bookkeeping
   - exit 0 for memory file writes, which are handled by write guard
4. Ensure catalog exists and is fresh enough.
5. Run `memory_surface.py search`.
6. If no results, exit 0.
7. In advisory mode, print JSON:

```json
{
  "suppressOutput": true,
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "additionalContext": "<memory-recall ...>...</memory-recall>"
  }
}
```

For `PreToolUse`, `additionalContext` is available to Claude before the next model step, alongside or after the tool result. It is not a pre-generation hint for the already-issued tool call. Therefore advisory mode cannot prevent the first matched tool execution; strict mode must deny before execution when that matters.

8. In strict mode, if high-confidence recall is unsatisfied, print JSON:

```json
{
  "suppressOutput": true,
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "Memory recall is required for this tool call. Read one relevant memory file from the recall result, then retry the tool call."
  }
}
```

Strict mode should also include a compact recall list in `permissionDecisionReason`, because that reason is shown to Claude.
The reason must include `path:` lines for the required memories and the instruction: read one listed memory, then retry the original tool call.

### 12.2 `memory-write-guard.sh`

Event:

```text
PreToolUse
```

Matchers:

```text
Edit|Write|MultiEdit
```

Behavior:

1. Read hook JSON from stdin.
2. Extract target path.
3. Exit 0 unless target is:
   - `memory/*.md`
   - `memory/_tags.json`
   - `memory/_tag_graph.json`
   - `memory/_path_tags.json`
4. For `Write`, validate proposed full content.
5. For `Edit` and `MultiEdit`, simulate the edit against the current file content, then validate.
6. If invalid, deny the write with `permissionDecision: "deny"` and a concise reason.
7. If valid, exit 0.

Validation failures:

- missing frontmatter on a memory file
- missing `tags`
- unknown tag
- generic denied tag
- too many tags
- invalid JSON taxonomy file
- graph conflict
- path rule references unknown tag

Unknown tags are allowed only after `_tags.json` already contains them. This forces Claude to expand the vocabulary deliberately before tagging a memory with a new token.

When denying a memory write for missing, unknown, deprecated, or denied tags, the denial reason must include:

- the exact invalid tag(s)
- up to 8 closest active tag matches by simple edit distance or prefix match
- a capped `<memory-tag-vocabulary>` excerpt of `_tags.json`, no more than 200 lines
- the instruction to add a genuinely new tag to `_tags.json` first, then retry the memory write

Optional strict write-vocabulary mode:

- config key: `requireVocabularySeenBeforeMemoryWrite`
- default: `false`
- when `true`, the first memory-file write attempt per session is denied with the capped vocabulary excerpt, even if the proposed tags are valid, so the model must retry after seeing the canonical vocabulary

### 12.3 `memory-catalog-refresh.sh`

Event:

```text
PostToolUse
```

Matchers:

```text
Edit|Write|MultiEdit
```

Behavior:

1. Exit 0 unless target path is in a memory directory.
2. Run `memory_surface.py validate`.
3. Rebuild `_memory_catalog.json` if validation succeeds.
4. If only individual memory files are invalid, rebuild `_memory_catalog.json` with those files listed under `invalidMemories` and omitted from retrieval.
5. If validation fails, return:

```json
{
  "suppressOutput": true,
  "decision": "block",
  "reason": "memory taxonomy validation failed: <short reason>",
  "hookSpecificOutput": {
    "hookEventName": "PostToolUse",
    "additionalContext": "memory taxonomy validation failed: <short reason>"
  }
}
```

PostToolUse cannot undo the write. It provides immediate correction pressure and keeps the catalog from silently drifting. `decision` and `reason` are top-level fields; `hookSpecificOutput` is only for event-specific context.

### 12.4 Strict-mode read ledger

Strict mode needs state to avoid loops.

Ledger path:

```text
${XDG_RUNTIME_DIR:-/tmp/claude-memory-surface-$UID}/recall-${session_id}.json
```

The directory must be created with mode `0700`. `session_id` comes from hook input `.session_id`; if absent, use `sha256(transcript_path)`; if both are absent, use `unknown` and keep entries short-lived.

Ledger entries:

```json
{
  "queryId": "memq_20260511_9f83",
  "queryHash": "sha256:...",
  "createdAt": "2026-05-11T12:34:56-07:00",
  "requiredMemoryIds": ["krdp_kcm_cert_bug"],
  "satisfied": false,
  "satisfiedBy": null
}
```

`queryHash` is `sha256(tool_name + "\0" + sorted(canonicalTags).join(",") + "\0" + normalized strong evidence tokens)`.

When a `Read` tool call targets one of the required memory paths, the recall hook marks the pending entry satisfied and allows subsequent matching tool calls. Reading one listed memory satisfies the recall in v1; a future stricter mode may require reading all listed memories. Ledger entries expire after `dedupeTtlSeconds` and are garbage-collected opportunistically.

Strict mode must never require recall before reading a memory file that would satisfy a pending recall. This is the loop-avoidance invariant.

Strict mode is not part of the first rollout. Implement the ledger only when enabling strict mode.

---

## 13. Prompt and instruction updates

Update `CLAUDE.md.fragment` memory section after the recall hook ships:

```md
## Memory consultation

Project memories are retrieved by a tool-call-triggered memory recall hook. When a `<memory-recall>` block appears, treat it as required project context for the current topic. Use the listed summaries before continuing. If a listed memory may change the action, read that memory file before proposing or editing.

Do not browse memory bodies by habit. The recall hook surfaces summaries only; read full bodies selectively when they are relevant.

When writing or refreshing a memory, use only tags from the project's memory `_tags.json`. Add a new tag to `_tags.json` first when a genuinely new concept is needed.
```

This replaces the current `MEMORY.md`-indexed instruction; do not keep both instructions active. Keep this static instruction in `CLAUDE.md.fragment`, not inside every hook injection. The hook block should be factual and compact.

---

## 14. Engine implementation details

### 14.1 Language

Use Python 3 for `memory_surface.py`.

Reason:

- The logic is stateful enough that shell plus `jq` would become fragile.
- Python stdlib is enough: `json`, `re`, `hashlib`, `datetime`, `pathlib`, `fnmatch`, `shlex`.
- Existing Memory Roulette already uses Python for stateful memory operations.

The hook wrappers stay shell scripts to match the Claude-Lab style and keep installation simple.

### 14.2 Performance budget

Warm no-match:

- target <= 30 ms
- hard cap <= 100 ms

Warm match:

- target <= 75 ms
- hard cap <= 200 ms

Stale catalog rebuild:

- target <= 300 ms for <= 200 memories
- hard cap controlled by hook timeout

Implementation tactics:

- Shell wrapper cheap-gates before Python when possible.
- Catalog cache avoids reparsing all memory bodies on every tool call.
- The engine reads only frontmatter and taxonomy files for rebuild.
- Search reads `_memory_catalog.json`, not memory bodies.

### 14.3 Frontmatter parser

Implement a small parser compatible with `_review_game.py`:

- frontmatter starts at byte 0 with `---\n`
- frontmatter ends at the next `\n---\n`
- key/value lines use the first `:`
- `tags` must be parsed from one-line flow-list syntax
- quoted descriptions are accepted as raw strings
- unknown keys preserved by writers outside this engine

Do not add a PyYAML dependency in v1.

### 14.4 Catalog fingerprint

`sourceFingerprint` should hash:

- sorted memory filenames
- memory file mtimes and sizes
- `_tags.json` contents
- `_tag_graph.json` contents
- `_path_tags.json` contents

The fingerprint is for staleness detection, not security.

Catalog rebuild writes must be atomic:

- acquire an exclusive lock at `_memory_catalog.lock`
- write JSON to `_memory_catalog.json.tmp`
- fsync and `os.replace` the temp file over `_memory_catalog.json`
- release the lock

Concurrent sessions must never expose a torn catalog file.

### 14.5 Output escaping

Surface XML-like blocks must escape:

- `&` as `&amp;`
- `<` as `&lt;`
- `>` as `&gt;`
- `"` in attribute values as `&quot;`

Descriptions are trusted local data but still escaped to avoid malformed context blocks.

### 14.6 Path and glob semantics

Path rule patterns are normalized at load time by expanding `~` to `$HOME` only. Do not expand arbitrary environment variables in rule patterns. Tool-call file paths are normalized the same way before matching.

`glob` path rules use Python `fnmatch.fnmatchcase` semantics. `?` and `[...]` are supported; recursive `**` is not supported in v1.

---

## 15. Validation rules

### 15.1 Memory file validation

Fail validation if:

- no frontmatter
- missing `name`, `description`, `type`, or `tags`
- `tags` is not one-line flow-list syntax
- any tag is unknown
- any tag violates token regex
- any tag is denylisted
- more than 8 tags
- duplicate tags after canonicalization
- description is empty

Warn, but do not fail, if:

- description exceeds 220 chars
- fewer than 2 tags
- tag count exceeds 5 but not 8
- `lastReviewed` is older than 180 days
- memory type is grandfathered but not in the allowed set
- a memory carries both sides of a distinction pair

Validate `MEMORY.md` separately after Phase 3:

- warn above 20 nonblank lines
- fail above 40 nonblank lines unless `MEMORY_SURFACE_ALLOW_LONG_INDEX=1`
- fail if it contains one line per memory after recall is enabled

### 15.2 Vocabulary validation

Fail validation if:

- invalid JSON
- schema version unsupported
- tag key violates token regex
- tag description has fewer than 6 words
- tag description exceeds 25 words
- active tag has no description
- deprecated tag has no `replacement` and no `reason`
- replacement tag is unknown
- denylist includes a currently active tag

### 15.3 Graph validation

Fail validation if:

- invalid JSON
- graph references unknown tags
- synonym member equals canonical
- synonym set duplicates a member
- a tag appears in more than one synonym set
- a pair is both synonym and distinction
- distinction mode is not `symmetric`
- graph canonicalization creates ambiguous canonical representatives

### 15.4 Path rule validation

Fail validation if:

- invalid JSON
- unknown `match`
- unknown `strength`
- empty pattern
- rule references unknown tag
- glob contains recursive `**` in v1

---

## 16. Rollout plan

### Phase 0 - Data preparation

Goal: tag the current corpus without changing retrieval behavior.

Tasks:

1. Create `_tags.json`, `_tag_graph.json`, and `_path_tags.json` in the memory directory.
2. Add `tags: [...]` to all existing memory files.
3. Run `memory_surface.py validate`.
4. Run `memory_surface.py rebuild`.
5. Confirm `_review_game.py status` still works.

Acceptance:

- all memory files validate
- Memory Roulette preserves `tags`
- `_memory_catalog.json` contains every memory
- no hook behavior has changed yet
- existing `MEMORY.md` is preserved only until recall injection ships

### Phase 1 - Write-time validation

Goal: prevent future tag drift.

Tasks:

1. Add `memory-write-guard.sh`.
2. Add `memory-catalog-refresh.sh`.
3. Register both hooks.
4. Test writes with valid and invalid tags.
5. Update README files.

Acceptance:

- unknown tags are denied before memory writes
- unknown-tag denials include closest matches and a capped vocabulary excerpt
- `_tags.json` edits are schema-checked
- `_tag_graph.json` conflicts are rejected
- catalog rebuilds after valid memory edits

### Phase 2 - Graph and catalog search

Goal: implement search without hook injection.

Tasks:

1. Implement graph canonicalization.
2. Implement path/command token extraction.
3. Implement search/ranking.
4. Add synthetic fixture payloads.
5. Verify expected memories rank first.

Acceptance:

- `krdpserver`/`krdp.service` queries return KRDP memory
- `~/.zshenv` queries return mosh locale memory
- `WarpPreview` paths return WarpPreview memory
- generic `git status`, `ls`, and broad `Read` calls return nothing

### Phase 3 - Advisory PreToolUse recall

Goal: inject bounded recall summaries.

Tasks:

1. Add `memory-recall.sh`.
2. Register it in `settings.global.fragment.json`.
3. Return `additionalContext` JSON on matches.
4. Deduplicate identical query hashes per session.
5. Replace the old `CLAUDE.md.fragment` memory instruction.
6. Convert `MEMORY.md` from a line-per-memory index into the capped memory router.

Acceptance:

- no-match calls are silent
- match calls inject at most 3 summaries
- hook output is valid JSON
- no memory body is injected
- descriptions are capped and escaped
- `MEMORY.md` no longer lists every memory

### Phase 4 - Tuning

Goal: reduce false positives and false negatives from real sessions.

Tasks:

1. Keep a local audit log under `/tmp` or disabled-by-default debug file.
2. Track surfaced query, tags, result ids, and whether a memory was subsequently read.
3. Tune `_path_tags.json`, graph distinctions, and stop tokens.
4. Run periodic user taxonomy passes.

Acceptance:

- false positives are rare enough not to annoy
- false negatives have clear path-rule or tag-graph fixes
- tag vocabulary stays readable in under 30 seconds

### Phase 5 - Strict mode, optional

Goal: enforce high-confidence recall before action.

Tasks:

1. Implement session ledger.
2. Deny high-confidence unsatisfied tool calls.
3. Mark recall satisfied on `Read` of a listed memory file.
4. Add escape hatch in config: advisory-only, strict-high-confidence, disabled.

Acceptance:

- no infinite denial loop
- generic tool calls are not blocked
- a relevant memory read permits retry
- strict mode can be disabled instantly

---

## 17. Tests

### 17.1 Unit tests

Add tests for:

- frontmatter parsing
- one-line `tags` parsing
- vocabulary validation
- graph conflict detection
- overlapping synonym-set rejection
- synonym canonicalization
- transitive synonym merge through `link`
- distinction penalties
- hard distinction guardrail for wrong-side generic evidence
- path rule matching
- Bash token extraction with quotes and separators
- WebSearch and WebFetch extraction
- ranking tie-breakers
- XML escaping
- block size caps
- atomic catalog write with concurrent rebuild attempts
- `MEMORY.md` router line-cap validation

### 17.2 Integration tests

Use synthetic hook payload files:

```text
tests/fixtures/hooks/bash-krdp-status.json
tests/fixtures/hooks/bash-git-status.json
tests/fixtures/hooks/read-zshenv.json
tests/fixtures/hooks/websearch-blink-mosh.json
tests/fixtures/hooks/write-memory-unknown-tag.json
```

Expected assertions:

- `bash-krdp-status` returns recall including `krdp_kcm_cert_bug`
- `bash-git-status` returns no recall
- `read-zshenv` returns recall including `mosh_locale_zshenv`
- `write-memory-unknown-tag` is denied
- every hook stdout path that emits JSON validates with `jq empty`
- memory directory resolution is stable when hook `cwd` differs from `transcript_path`
- configured matchers do not fire on `NotebookRead` or `NotebookEdit`
- PostToolUse validation uses top-level `decision` and `reason`
- strict-mode flow denies, then allows retry after reading one listed memory file

### 17.3 Regression tests from reverted injector

Verify the old failure mode does not return:

- user prompt text alone cannot trigger recall
- descriptions do not cause substring matching against the user prompt
- memory bodies are never inlined by recall hook
- broad terms like `config`, `linux`, and `tool` cannot become active tags

### 17.4 Manual smoke tests

Commands:

```sh
python3 ~/.claude/projects/-home-jangman/memory/_review_game.py status
python3 Claude-Lab/lib/memory_surface.py validate --memory-dir ~/.claude/projects/-home-jangman/memory
python3 Claude-Lab/lib/memory_surface.py rebuild --memory-dir ~/.claude/projects/-home-jangman/memory
Claude-Lab/install.sh
Claude-Lab/install.sh --apply
```

Hook payload tests:

```sh
Claude-Lab/hooks/memory-recall.sh < tests/fixtures/hooks/bash-krdp-status.json | jq .
Claude-Lab/hooks/memory-write-guard.sh < tests/fixtures/hooks/write-memory-unknown-tag.json | jq .
```

---

## 18. Security and privacy

Requirements:

- Do not surface memory bodies automatically.
- Do not surface memories across project boundaries.
- Do not read arbitrary files during recall except taxonomy files and generated catalog.
- Do not execute shell command payloads; parse only.
- Do not expand command substitutions or environment variables from Bash payloads.
- Escape all surfaced text.
- Fail open for retrieval errors.
- Fail closed for taxonomy writes.
- Keep debug logs local and disabled by default.

The memory corpus is local trusted data, but descriptions can still contain stale or misleading text. The recall block is evidence, not authority; the model still verifies time-sensitive claims before acting.

Fail-open retrieval cases:

- missing memory directory: no output
- missing catalog: rebuild if cheap-gate found a plausible signal, otherwise no output
- missing `_tags.json` during Phase 0 bootstrap: allow writes that create taxonomy files, but do not surface recall
- invalid catalog JSON: no recall, debug log only
- Python timeout: no recall, debug log only
- invalid individual memory file: omit it from recall and list it in `invalidMemories`

Fail-closed write cases:

- invalid memory frontmatter after bootstrap
- unknown active tags after `_tags.json` exists
- graph conflicts
- path rules referencing unknown tags

Emergency kill switch:

```text
~/.claude/projects/<project-key>/memory/.surface-disabled
```

If this zero-byte sentinel exists, all memory-surface hooks exit 0 before spawning Python.

---

## 19. Observability

Default mode: no persistent logs.

Debug mode:

```sh
MEMORY_SURFACE_DEBUG=1
```

Debug log path:

```text
${XDG_RUNTIME_DIR:-/tmp/claude-memory-surface-$UID}/debug-${session_id}.jsonl
```

Each line:

```json
{
  "ts": "2026-05-11T12:34:56-07:00",
  "toolName": "Bash",
  "queryHash": "sha256:...",
  "tokens": ["krdp", "systemctl"],
  "tags": ["krdp", "remote-access", "systemd"],
  "results": ["krdp_kcm_cert_bug", "remote_access_doc"],
  "emitted": true,
  "elapsedMs": 42
}
```

Never log full memory bodies or full command payloads by default.

---

## 20. Configuration

Optional config file:

```text
~/.claude/projects/<project-key>/memory/_memory_surface_config.json
```

Defaults:

```json
{
  "schemaVersion": 1,
  "enabled": true,
  "mode": "advisory",
  "maxResults": 3,
  "maxDescriptionChars": 220,
  "maxBlockChars": 4000,
  "dedupeTtlSeconds": 900,
  "confidenceHighThreshold": 5,
  "confidenceMediumThreshold": 3,
  "requireVocabularySeenBeforeMemoryWrite": false,
  "debug": false
}
```

Allowed modes:

- `disabled`
- `advisory`
- `strict-high-confidence`

If config is absent, use defaults.

---

## 21. Initial taxonomy seeding guidance

The first pass should tag existing memories conservatively. Use 3-5 tags each. Prefer tags that map to future tool-call signals.

Seed tag families likely needed by the current corpus:

```text
archinstall
blink
claude-code
controller
firewalld
kde
kde-wayland
kitty
krdp
kwallet
locale
mosh
nvidia-wayland
plasma
proton
qtquick
remote-access
shell
steam
sunshine
systemd
tailscale
terminal-theme
warp
warp-preview
zsh
```

Do not add every seed blindly. Add only tags used by at least one memory or path rule.

---

## 22. Acceptance criteria for v1

The implementation is complete when:

- every existing memory has valid `tags`
- `_tags.json`, `_tag_graph.json`, `_path_tags.json`, and `_memory_catalog.json` exist
- unknown tags are rejected on memory writes
- graph conflicts are rejected
- `PreToolUse` recall surfaces summaries for strong tool-call matches
- generic tool calls remain silent
- no memory body is auto-loaded
- recall blocks are capped at 3 results and 4000 chars
- `MEMORY.md` is a capped router, not a full memory index
- `CLAUDE.md.fragment` tells Claude how to use recall blocks
- installer dry run shows the new hooks
- tests cover validation, extraction, ranking, and hook JSON output

---

## 23. Explicit implementation non-goals

Do not build these in v1:

- embeddings
- vector databases
- LLM-based tag assignment
- automatic graph merging
- body inlining
- prompt-substring matching
- global cross-project recall
- network calls from hooks
- background daemons
- MCP server

If a future version adds any of these, it must preserve the same bounded surface contract.

---

## 24. Build order checklist

1. Add `Claude-Lab/lib/memory_surface.py` with `validate`, `rebuild`, `search`, `link`, and `unlink`.
2. Add unit fixtures and tests.
3. Seed `_tags.json`, `_tag_graph.json`, `_path_tags.json`.
4. Tag all existing memory files.
5. Rebuild `_memory_catalog.json`.
6. Add `memory-write-guard.sh`.
7. Add `memory-catalog-refresh.sh`.
8. Register validation hooks and run installer dry-run.
9. Add `memory-recall.sh` in advisory mode.
10. Register recall hook and run installer dry-run.
11. Replace the `CLAUDE.md.fragment` memory instruction and update README.
12. Convert `MEMORY.md` to the capped router.
13. Run synthetic hook tests.
14. Apply installer.
15. Observe real sessions and tune path rules before considering strict mode.

---

## 25. Final design stance

This system should feel like a library catalog, not a second brain. The user curates the subject headings. Hooks route concrete tool-call evidence through those headings. Claude sees only the checkout slip unless it deliberately opens a book.

The erosion-resistant property comes from three constraints held together:

- the catalog can grow, but the surface cannot
- the graph can correct model priors, but only through explicit user-readable edges
- Claude can write memories, but it cannot invent retrieval vocabulary casually
