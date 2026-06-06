# Memory surfacing spec comparison

<!-- handoff-scope: claude -->

**Status:** Lightweight arbiter comparison.  
**Created:** 2026-05-11.  
**Previous spec:** `2026-05-11-memory-surfacing-implementation-spec.md`.  
**Rerun spec:** `2026-05-11-memory-surfacing-implementation-spec-rerun.md`.  
**Comparison agents:** Claude CLI `haiku` alias after explicit `Haiku-4.5` and `Sonnet-4.6` strings were rejected; Codex CLI `gpt-5.4-mini`.

## Verdict

Both comparison agents selected the rerun spec as the stronger implementation base.

Reason: the rerun spec makes MUST-use enforcement concrete through obligations, read satisfaction, dismissal, and retry flow. It is also shorter, easier to follow, and has clearer hook choreography, rollout, validation, failure modes, and acceptance criteria.

## Improvements In The Rerun Spec

- First-class obligation model for high-confidence recall instead of deferring strict mode as an optional later layer.
- Clearer separation of hook responsibilities: recall, obligation guard, read satisfaction, write context, write guard, catalog refresh.
- Human-readable Markdown taxonomy files (`_tags.md`, `_tag_links.md`) better match the user's taxonomy-curator workflow.
- More concrete denial, read, dismiss, and retry behavior.
- Better phase-by-phase build order and acceptance criteria.
- Stronger failure-mode table and emergency kill switch.

## Regressions Or Gaps

- Path-tag rules are embedded in `_tag_links.md`, but the spec still references path-tag validation in ways that may imply a separate path-rule artifact. Choose one authoritative location and make the parser/validation rules match it.
- Required-read policy is inconsistent: the cap allows two required reads, but the v1 read-satisfy rule says one read satisfies unless `requireAllRequiredReads=true`. Collapse this to a single rule.
- Performance budgets are less explicit than the prior spec. Restore targets such as warm no-match <=50ms and warm match <=150ms.
- Markdown taxonomy improves readability but increases parser brittleness. Keep grammar frozen and heavily tested if Markdown remains source-of-truth.
- Token extraction is less detailed than the prior spec's per-tool examples. Reintroduce concrete Bash/package/systemd/path examples.
- Memory Roulette compatibility should be stated more explicitly, including unknown frontmatter preservation and review fields.
- Denylist mechanism is less concrete than the prior JSON policy. Add exact Markdown syntax or use a small generated/internal denylist table.
- Query dedupe should define `queryHash`, not only TTL.

## Recommended Merged Direction

Use the rerun spec as the base.

Before implementation, patch the rerun spec or implementation plan to:

- make path-tag storage unambiguous
- define one required-read policy
- restore explicit performance budgets
- restore detailed token-extraction examples
- explicitly preserve Memory Roulette frontmatter behavior
- freeze and test the Markdown taxonomy grammar
- define generic-tag denylist syntax
- define `queryHash` for dedupe and obligation identity

The previous spec remains useful as a detail reservoir, especially for Claude Code hook semantics, session-based memory directory resolution, performance budget language, and test coverage breadth.
