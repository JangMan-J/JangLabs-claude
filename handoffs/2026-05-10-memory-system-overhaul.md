# Memory system overhaul — rough draft

<!-- handoff-scope: claude -->

**Status:** Draft. Captured from a session conversation on 2026-05-10. Not a spec — a faithful record of the design discussion, decision space, and open questions. Edit deliberately; do not casually rewrite.

**Scope:** The `~/.claude/projects/-home-jangman/memory/` system. Specifically: how memories get *surfaced* (retrieval), how they get *kept fresh* (already partially solved — see anchors at bottom), and how the system can grow without eroding Claude's effective context.

**Audience:** A future session (Claude or human) picking this up cold. The "we" voice below is the conversation pair, captured for posterity; it is not a directive to the reader.

---

## Vision

**In one sentence:** A memory system where Claude's capability *compounds* across sessions without ever *eroding* per-session capability — because the catalog grows but the surface stays compact.

**Framed against what it isn't:**

| Not | Is |
|-----|-----|
| RAG | A curated taxonomy with hand-cut edges |
| Embeddings | Explicit synonym/distinction graph the user can read in 30 seconds |
| "AI memory" | A library catalog with a strict-budget checkout policy |
| Auto-everything | Structural forcing functions where Claude cannot be trusted to remain consistent across sessions |
| Unbounded weight | Three layers, each with a cap, each with a single owner |

**The aesthetic.** The user is a taxonomy curator, not a data-entry clerk. Their work is *judgment*, not *labor*: deciding when two tags merge, when an entry is dead, when training-data prior is wrong. Claude does the rote work (writing memory bodies, applying tags from the vocabulary, surfacing on tool calls). The forcing functions exist so Claude cannot accidentally degrade the curation while doing the rote work.

**What success looks like, concretely.**

- *One year from now:* the corpus is ~80 memories and Claude's per-turn context carries the same weight from `MEMORY.md` it does today (~17 lines, ~3KB), because retrieval is tool-call-routed, not index-skim.
- *Three years from now:* the corpus has been pruned by the user from a peak of ~150 entries down to ~60 via ruthless taxonomy passes. Half the original entries have died via Memory Roulette; the survivors got merged via synonym-graph consolidation. The system has gotten *smaller and sharper* over time, not larger.
- *At no point* did a snowball form.

**The single architectural principle.** Whatever is unbounded must not cross the prompt boundary. Whatever crosses the prompt boundary must be hard-capped. The synonym graph is the load-bearing trick — it lets the unbounded thing (the catalog) be queried *through the user's mental model* (the graph) before being filtered down to the bounded thing (the surface).

**The single human-discipline ask.** Periodic taxonomy curation. Bounded in scope (a few minutes, every few months). Bounded in cognitive load (read a flat list, merge or distinguish, sometimes describe). This is the one piece that *cannot* be automated without re-introducing the snowball.

---

## Why this exists

The user has already lived through one cycle of "snowball-effect memory harness" erosion: a memory system that started useful, grew unchecked, and degraded Claude's output by pulling attention and context budget away from the live task. The current system on this box is at 17 memories and still working — but the soft-prior consistency model that holds it together does not scale. Two scaling failures were named explicitly in conversation:

1. **Index-skim dropout.** `MEMORY.md` is always-loaded. At small N (~17 entries), each line gets meaningful attention. At larger N (~150+), individual entries compete for attention with everything else in the prompt and lose. There is no mechanism that *forces* a per-turn skim; it relies on Claude's discipline, which is not durable across sessions.
2. **Stale memory served confidently.** A 2026-05 memory about a Plasma 6.6.4 quirk will still feel authoritative in 2027 under Plasma 6.9 unless the model bothers to verify. The CLAUDE.md "before recommending from memory, verify" rule is the only guardrail and it is, again, soft discipline.

A third failure mode — memory contradiction at high N — exists but is downstream of the first two.

The Memory Roulette game (already built — see Anchors) addresses failure mode #2 by gamifying review cadence. **This handoff addresses failure mode #1** by replacing prose-skim retrieval with structured, tag-routed, tool-call-triggered retrieval.

---

## Design pillars (mission-critical, non-negotiable)

These three principles surfaced repeatedly. Anything proposed below that violates one of them needs to be revisited.

### 1. Compact ceilings are baked in everywhere

Every artifact that gets *surfaced into Claude's context* must have a hard cap on size and frequency. The catalog being retrieved from can grow without bound — what is loaded per retrieval cannot. Examples of where ceilings apply:

- Max memories surfaced per tool-call retrieval event (proposed: 3)
- Max characters per surfaced memory description (proposed: ~150, matching current MEMORY.md hook lines)
- Max retrievals per turn (proposed: 1 per distinct PreToolUse fire, dedup'd)
- Max tag vocabulary entries shown when the model needs to pick tags during a memory write (proposed: full list always-in-context, but with a hard ~200-line truncation rule, mirroring the existing MEMORY.md truncation behavior)
- Max length of a single memory body (existing memories already trend ~50-200 lines; no need for a new cap, but worth tracking)

The user is explicit: the *triage process itself* needs a compact ceiling. Spending 20% of every turn deciding whether a memory is relevant is itself the failure mode being prevented.

### 2. Catalog: unbounded. Surface: bounded.

The one part of the system that can grow pragmatically forever is the **tag↔memory mapping table plus the synonym/distinction graph**. This table lives in a data file consulted by a hook — it is not loaded into Claude's prompt. Its size is irrelevant to Claude's context. The model only sees the *result* of querying it, which is bounded by the surface cap.

This is the same shape Anthropic already shipped for tools: deferred-tool names are always visible (small), full schemas are lazy-loaded via ToolSearch (larger, but on-demand and capped). The recipe is already in this codebase — see the ToolSearch tool that surfaced earlier in this session. We are transposing it from tools to memories.

### 3. Triggered by tool-call context, not by user prompt

A previous experiment auto-surfaced memories by substring-matching the user's prompt. It was rolled back — false-positive rate was too high at small corpus size, and the matching signal (a vague prompt) was too noisy. The lesson: **the better signal is what Claude is about to *do*, not what the user asked for.**

A tool call payload is concrete: a command name, a file path, a search query, a library name. Tokens extractable from a tool call match cleanly against a tag set. Tokens extractable from a user prompt match against half the world.

Therefore: the retrieval hook fires on `PreToolUse`, not on `UserPromptSubmit`.

---

## The proposed architecture

### Substrate: tags on every memory

Every memory file gains a `tags:` field in its frontmatter:

```yaml
---
name: KRDP KCM cert-path persistence bug
description: ...
type: project
tags: [kde, plasma, krdp, kwallet, remote-desktop]
---
```

Tags are tokens, not prose. They are the retrieval keys. Their granularity is roughly "software project, subsystem, or hardware/component" — not too generic (`config`, `linux` — useless because they match everything) and not too narrow (`krdpserverrc-file` — useless because nothing else will ever match it).

### Catalog: a tag vocabulary + synonym/distinction graph

Two artifacts live outside the prompt, consulted by hooks:

**A. Tag vocabulary** (`memory/_tags.md` or `Claude-Lab/data/tags.json` — TBD).
A flat list of every tag in current use, with a one-line description per tag. This is the canonical vocabulary. New tags only enter via deliberate addition — the write-time hook (see below) blocks unknown tokens.

The vocabulary file *is* always-in-context (under the truncation cap), so Claude sees the existing vocabulary when writing a new memory and is steered toward reusing existing tags rather than inventing new ones. This is the structural forcing function for tagging discipline that Claude's cross-session memory cannot provide.

**B. Synonym/distinction graph.**
This is the load-bearing innovation. It is a **user-curated** declaration of semantic relationships between tags that *correct the implicit weights present in the model's training data*.

Two kinds of edges:

- **Synonym edges:** "these two tokens should be treated as the same tag for retrieval purposes." Example: `kwin ↔ plasma-compositor`. The model's training prior likely already conflates these; the synonym edge just confirms it for the hook's matcher.
- **Distinction edges:** "these two tokens are *not* synonyms even though training data conflates them." Example: `claude-code` vs `claude-cli` (the former is the Anthropic CLI, the latter is sometimes the same and sometimes a community tool — context-dependent). Or `kde-wayland` vs `kde-x11`: a memory tagged `kde-wayland` should NOT surface when the tool call is in X11 context, even if training data treats them as roughly the same surface.

The graph is *small* by design (small enough for the user to read and maintain by hand). It is *not* an embedding model. It is an explicit override layer for the cases where training-data weight is wrong for this user's mental model.

The file format is open — could be a Markdown table, a JSON object, a flat `kwin = plasma-compositor` and `claude-code != claude-cli` text file. The user's preference will drive this.

### Trigger: PreToolUse hook with model-selected token extraction

For each tool call type, the hook extracts retrieval tokens from the payload:

| Tool | Tokens extracted |
|------|------------------|
| Bash | First command word; first non-flag arg; any absolute paths mentioned |
| Read / Edit / Write | The absolute file path (matched against tag rules mapping paths→tags, e.g. `~/.zshenv` → tags `shell, zsh, locale`) |
| WebSearch / WebFetch | The query string, tokenized; the URL hostname |
| `mcp__plugin_context7_context7__*` | The library/package name |

Generic tools (`Read` of a one-off file, `ls`, `grep`) emit weak signals and may be skipped to avoid noise.

The hook then:

1. Canonicalizes each token through the synonym graph (e.g. `plasma` → `kwin` if the canonical form is `kwin`).
2. Drops distinguished tokens that conflict with the current tool-call context (if extractable — TBD how).
3. Queries the catalog for memories whose `tags:` intersect the canonicalized set.
4. Ranks (proposed: by intersection size first, then by recency-of-relevance; *not* by mtime, which is a staleness signal, not a relevance signal).
5. Surfaces up to N memories' descriptions (≤3 by default, hard-capped).

The output format mirrors ToolSearch results: a small block of `name + description` entries that Claude can choose to read in full via a follow-up Read on the memory file. **Bodies are never auto-loaded.** The model decides which (if any) to actually pull, and that decision is part of the bounded-surface budget.

### Repurposed ToolSearch as the API surface

Two design options for how the retrieval surfaces:

**Option A — Hook injects a system-reminder.**
PreToolUse hook resolves the query and injects a `<memory-recall>` block into Claude's context. Claude sees it before the tool result returns. Mirrors how `UserPromptSubmit` hooks work today.

**Option B — Hook exposes a `MemorySearch` tool that Claude calls explicitly.**
The PreToolUse hook is replaced (or supplemented) by Claude being trained (via skill / CLAUDE.md prompt) to invoke `MemorySearch` itself, much like ToolSearch. The query is the model's own extracted tokens.

Option A is more autonomous (zero discipline required) but firmer (always fires). Option B is more idiomatic (matches the existing ToolSearch pattern) but reintroduces a discipline requirement.

Probable answer: **start with A, allow B as an escape valve** for cases where the hook didn't match but the model knows more memories might be relevant. The two are complementary — A handles the common case structurally; B handles the long tail without requiring a hook author to anticipate every signal.

---

## The discipline question (resolved)

A recurring thread in the conversation: who owns the discipline that makes this work?

The structural answer is: **as little discipline as possible should be required of Claude across sessions**, because Claude has no cross-session memory of its own past tagging decisions. Anything that depends on Claude "consistently using tag X across many sessions" is the soft-prior failure mode rebuilt. So:

- **Tag consistency at write time:** enforced by a `PostToolUse` hook on `Write` / `Edit` to `memory/*.md`. Parses frontmatter, validates each tag against the vocabulary file, blocks (with helpful error) on unknown tokens. Unknown tokens can only be added by Claude deliberately *also* editing the vocabulary file in the same turn.
- **Vocabulary visibility at write time:** the vocabulary file is structured to be readable in <30 seconds and is loaded into context when Claude is about to write a memory. (Implementation TBD: maybe inject it via the `Write`-matched PreToolUse hook only when the target path is under `memory/`.)
- **Synonym graph maintenance:** explicitly delegated to the user. Periodic pruning, conflict resolution, deciding when "kwin" and "plasma-compositor" should merge or split — these are taxonomy judgments that benefit from a human and can't be safely automated. This is the one piece of human discipline that remains, and it is bounded (a few minutes every few months, not per-session).
- **Memory hygiene:** the Memory Roulette game (already built) handles staleness review. No additional Claude discipline required.

---

## How this interacts with what's already built

The Memory Roulette implementation from earlier in this session is **substrate-compatible** with this design:

- It already adds frontmatter fields to existing memory files (`lastReviewed`, `declineCount`, `nextEligible`).
- It already preserves unknown frontmatter fields on round-trip (the originSessionId field on each memory survives both keep/refresh and later/toss operations).
- Therefore, adding `tags:` to frontmatter does not conflict with the game's state mutations.

Conceptually:
- **Memory Roulette** = "is this memory still true / useful?" (staleness axis)
- **Tag-routed retrieval** = "is this memory relevant to what I'm about to do?" (retrieval axis)
- They share the frontmatter substrate, the file index, and the same set of operations (keep / refresh / toss).

---

## Open design questions (not yet decided)

These came up but were not resolved. Future sessions can answer them; do not invent answers without checking back.

1. **Tag vocabulary file format.** Markdown with a tag-per-line + description? JSON object keyed by tag? YAML? Trade-off: human-editability vs hook-parseability. Markdown leans toward human; JSON leans toward hook. The synonym graph could share format or be separate.
2. **Where does the vocabulary / synonym table live?**
   - Inside `memory/` (data co-located with memories) — pro: lives with what it indexes.
   - Inside `Claude-Lab/` (data co-located with the harness that uses it) — pro: tracked by the install.sh workflow, can be versioned with the hooks.
   - Probable answer: inside `Claude-Lab/data/` since the hooks live there, but TBD.
3. **Tag granularity policy.** What's "too generic"? What's "too narrow"? A short style guide in the vocabulary file would help future memory-writers.
4. **Per-tool-call surface cap.** 3 memories was the proposed default. Should it vary by tool? (E.g. a Bash call may legitimately touch 5 topics; a Read of a specific file usually touches 1.)
5. **Memory ranking when multiple match.** Intersection size first — but ties? By Memory Roulette `lastReviewed` (favor fresh)? By `declineCount` (penalize ignored memories)? By frontmatter `type` (favor `[Fumble]` and `[Method]` over `reference`)?
6. **Distinction-edge semantics.** A synonym edge is symmetric. Is a distinction edge symmetric too? Or directional? ("`claude-code` is not `claude-cli`, but `claude-cli` *might* be `claude-code`.")
7. **Anti-generic-tag enforcement.** The vocabulary itself can drift into uselessness if Claude adds tags like `config`, `linux`, `tool`. Either the user catches these on review, or the validator hook has a denylist. Denylist scales worse; user review scales better but requires the discipline we're trying to avoid. Maybe: any tag added by Claude requires a 1-line description, and a tag with a description shorter than 6 words OR matching a denylist pattern is rejected. TBD.
8. **Interaction with the existing `originSessionId` frontmatter.** Currently every memory has one. Should `tags:` insertion preserve order, or normalize key order? (Current Memory Roulette engine preserves unknown keys at the end; that's probably fine.)
9. **Catalog rebuild.** When the synonym graph changes (user merges two tags), do all memories need re-tagging? Or does the hook resolve through the graph at query time? Probable answer: resolve at query time, never modify memory files for graph changes — keeps the graph cheap to evolve.
10. **The "Other" Option-B Claude-invoked search.** If Claude can ask `MemorySearch` explicitly, what's the prompt that teaches Claude *when* to do that without it becoming a per-turn habit? This is itself a soft-prior problem — gives me pause about doing Option B at all.

---

## Phased implementation plan

A suggested ordering, smallest-blast-radius first. Each phase is independently useful and can stop here if benefits don't materialize.

**Phase 0 — Tag the existing corpus (manual, one-shot).**
Add `tags: [...]` frontmatter to all 17 existing memories. Build the initial vocabulary file from the union of tags used. No hooks yet; this is just data preparation. Output: working vocabulary file + tagged memories. This phase is reversible (revert the frontmatter edits if it doesn't feel right).

**Phase 1 — Write-time validation (forcing function).**
PostToolUse hook on `Write`/`Edit` to `memory/*.md` that validates the `tags:` field against the vocabulary file. Blocks unknown tokens (with a helpful error pointing at the vocabulary file). Now: future memories cannot drift in tag choice without Claude+user deliberately expanding the vocabulary.

**Phase 2 — Synonym graph + canonicalizer.**
Add the synonym/distinction graph. A small library function (probably Python, living next to the Memory Roulette engine) that takes a token and returns the canonical tag plus any distinctions to enforce. No retrieval yet, just the resolution layer.

**Phase 3 — Tool-call retrieval (the main event).**
PreToolUse hook that extracts tokens, canonicalizes, queries, surfaces ≤N descriptions. Iteratively tune which tools to hook (start with `Bash`, `Read`, `WebSearch`; expand if useful), the per-tool token extraction, and the surface cap.

**Phase 4 — Tuning.**
Watch real sessions, observe false positives (irrelevant surfaces) and false negatives (memories that should have surfaced but didn't), and adjust. Possibly add Option B (Claude-invoked `MemorySearch`) if Phase 3 leaves obvious gaps.

Phase 0 + Phase 1 alone is probably the smallest version that's worth shipping; it just adds writers' discipline without changing the retrieval flow. Phases 2-4 are the more ambitious part.

---

## What this design explicitly does *not* do

Worth stating, because they were considered and rejected:

- **No embedding-based retrieval.** Embeddings are unbounded weight, and the user's stated burn is "unbounded weight in the memory system." The explicit synonym graph is the deliberate downgrade from embeddings to something the user can read and edit.
- **No prompt-substring matching.** Already tried, already rolled back. Tool-call signal only.
- **No always-loaded memory bodies.** Only descriptions cross the surface boundary. Bodies are pulled by deliberate Read after the description suggests relevance.
- **No automatic vocabulary expansion.** Every new tag requires deliberate user/Claude action — adding it to the vocabulary file. Friction is the feature.
- **No "smart" ranking by ML.** Intersection size + a few hand-picked tiebreakers (frontmatter type, Memory Roulette state). The ranker is a 20-line function, not a model.

---

## Anchors — what already exists on this box (as of 2026-05-10)

- `~/.claude/projects/-home-jangman/memory/MEMORY.md` — current flat index, 17 entries, always-in-context.
- `~/.claude/projects/-home-jangman/memory/*.md` — 17 individual memory files with frontmatter (`name`, `description`, `type`, sometimes `originSessionId`). Will gain `tags:` in Phase 0.
- `~/.claude/projects/-home-jangman/memory/_review_game.py` — Memory Roulette engine. Frontmatter-aware. Idempotent. Test surface: `python3 _review_game.py status`.
- `~/.claude/hooks/memory-review-offer.sh` (symlink → `Claude-Lab/hooks/`) — UserPromptSubmit hook that probabilistically surfaces a review round when something is overdue.
- `~/.claude/skills/memory-review/SKILL.md` — protocol for Claude when a review round fires.
- `~/.claude/commands/play.md` — `/play` slash command for manual review rounds.
- `Claude-Lab/settings.global.fragment.json` — registered the review hook for install.sh idempotency.

Reading these in order tells you what's already wired and what this handoff would build on top of.

---

## Closing note

The architectural insight that drove this design is not novel. It is the **ToolSearch pattern transposed from tools to memories**: a small always-loaded routing index, an unbounded lazy-resolved catalog behind it, and explicit query syntax with hard caps on results. Anthropic already shipped this pattern for tools because they hit the context-budget wall first. We are following them across the same wall for a different artifact type.

The novelty is the **user-curated synonym/distinction graph as a semantic correction layer over training-data priors**. That part has no direct analog in the existing tooling. If it works, it is the piece worth writing up later.
