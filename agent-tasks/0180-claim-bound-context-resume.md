# 0180: Claim-bound context and resume handoff

- **Status:** Complete
- **Milestone:** v0.5.1 Trace & Efficient Handoff
- **Priority:** P0
- **Size:** M-L
- **Dependency:** 0179 source-binding validation
- **DB schema:** remains 8

## Goal

Let a receiving session navigate a valid intent index from context and resume
outputs through bounded, source-addressable **unverified** claim references,
without inlining the trace or confusing model output with verified facts.

## Scope

1. Add the 0178 optional claim-ref field to the packaged context/handoff
   contracts and Markdown rendering.
2. Populate it only from a source-bound index that passes 0179 validation.
3. Order items deterministically and apply an explicit item/byte budget.
4. Record omitted item IDs and reasons such as budget, unsupported item shape,
   invalid binding, or explicit non-selection.
5. Keep each emitted claim labeled unverified and retain exact Evidence/path/
   line references needed to inspect copied source lines.
6. Preserve no-index, invalid-index, and older packet behavior.

## Invariants

- Transcript text and source-line text are not inlined.
- Claim wording never enters `verified`, Decision approval, or next-action
  authority merely because it appears in an index.
- Selection is deterministic and does not call an LLM.
- `pcl context pack` and `pcl resume` remain read-only.
- No schema migration or first-class Trace/Intent entity.

## Acceptance

1. Valid fixtures emit deterministic unverified claim refs with resolvable
   copied-source locations.
2. Invalid or ambiguous binding emits no claim refs and preserves the typed
   diagnostic/safe stop.
3. Tight budgets produce deterministic omissions without partial items.
4. Full-transcript sentinels never appear in JSON or Markdown output.
5. Existing valid handoff-packet/v1 fixtures without the optional field remain
   valid and byte-stable where the trace feature is absent.
6. Targeted tests, full lint/test, strict validation, render, and packaged
   contract checks pass.

## Non-goals

- Automatic transcript capture or indexing.
- Semantic search, embeddings, or model-based ranking.
- Automatic execution of an indexed action.

## Completion evidence

- `docs/evidence/0180-claim-bound-context-resume.md`
