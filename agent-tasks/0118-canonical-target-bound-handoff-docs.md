# 0118: Canonical target-bound handoff docs (README + adoption)

Milestone: v0.3.1 Handoff Integrity + Operator Experience
Priority: P1
Area: docs
Origin: third-party v0.3.0 post-release review (P1③ — README does not surface
v0.3's canonical `--require-bound-receipt` flow). Sakamoto approved 2026-07-09.
Implemented by the orchestrator (opus) directly, not delegated — README/adoption
copy is user-facing, where taste matters more than throughput.

## Problem

v0.3.0's headline value is the target-bound context pack, gated by
`pcl context pack --include-code-context --require-bound-receipt`. But the README
front door (`## Context Packs`, `## Explainable Code Context`) shows only the
basic `pcl context pack --task ...` and `pcl impact --diff --json` forms, so a
first-time reader never sees the canonical strict handoff. `grep` on README for
`--require-bound-receipt` / `--for-task` / `--include-code-context` returns zero.

## Scope (orchestrator-owned files only)

Disjoint from 0119 (which owns `src/`, `tests/`, and the new
`docs/context-check.md`). This task edits only:

- `README.md`: add a short "Target-bound agent handoff (v0.3)" subsection near
  `## Context Packs` / `## Explainable Code Context` showing the canonical
  command for a task and a job:
  ```
  pcl index build --json
  pcl impact --diff --for-task T-0001 --json
  pcl context pack --task T-0001 --include-code-context --require-bound-receipt --json
  ```
  State plainly: with `--require-bound-receipt` the pack fails
  (`context_pack_bound_receipt_required`) instead of silently using an unrelated
  latest receipt; binding is a caller assertion (`caller_asserted`), not a
  relevance proof.
- `docs/context-pack.md`: mark `--require-bound-receipt` as the canonical strict
  handoff path for worker handoffs.
- `docs/code-context.md`: add a short "review/continuation vs pre-work" boundary
  note — receipts are built from `pcl impact --diff`, so a target-bound receipt
  presumes a diff exists; pre-implementation handoff is a separate future path.
- `docs/adoption-guide.md`: add the worker-handoff command as the recommended
  default.

## Invariants (what to protect)

- Docs only. No `src/`, no `tests/`, no schema, no behavior change.
- Every command shown must be one that actually exists and works in v0.3.0
  (verify by running each in a scratch repo before claiming it).
- Do not document `pcl context check` here — it does not exist until 0119 merges
  (a follow-up may cross-link once both are in).
- Keep the epistemic framing: no "safe"/"verified"/"understood" language; the
  pack records that a receipt was created for a target, not that it is
  sufficient.

## Acceptance

- README contains the canonical task and job handoff commands and the
  `--require-bound-receipt` semantics; `grep` for `--require-bound-receipt` in
  README is non-empty.
- The three docs carry the canonical-path / boundary notes.
- Each shown command verified against a live scratch repo (paste evidence in the
  commit or handoff).
- No code or test files changed.
