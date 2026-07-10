# 0142: Lifecycle repair planner for existing projects

- **Status:** Approved implementation slice
- **Milestone:** v0.4.1 Integrity Migration
- **Priority:** P1
- **Estimated size:** L
- **Dependencies:** 0140b (lifecycle findings and mutation guards), 0141
- **Parallel-safe with:** none of 0143–0145; this task establishes the repair-plan contract used by 0143 and touches shared CLI/validator surfaces
- **DB schema:** remains 8

## Problem

v0.4.0 prevents new false-completion states, but an existing project can still
contain terminal rows that predate the stronger lifecycle contract. Strict
validation can identify those rows, yet operators currently have to infer a
repair sequence from prose errors. Blindly changing statuses or choosing a
Story, Evidence item, Verification, or human decision would manufacture
semantics that the harness does not know.

## Goal

Add a deterministic, wholly read-only lifecycle repair planner. It classifies
each inconsistent row and shows concrete inspection or later repair commands,
but owns no mutation path or link mutation service.

## CLI contract

```text
pcl repair lifecycle [--dry-run] [--json]
```

- Bare `pcl repair lifecycle` and explicit `--dry-run` are equivalent
  read-only operations.
- Planning never writes the DB, events/outbox/JSONL, reports, dashboard, copied
  Evidence, or any other file.
- The command never executes a command string from its own output.
- All mutation modes belong to task 0143, which consumes this task's public
  action model in one direction.

The JSON result uses an additive, versioned `lifecycle-repair-plan/v1` shape:

```json
{
  "contract_version": "lifecycle-repair-plan/v1",
  "mode": "plan",
  "mutated": false,
  "summary": {
    "structural": 0,
    "semantic": 1,
    "human_review": 0,
    "unsupported": 0
  },
  "actions": [
    {
      "action_id": "LR-0001",
      "finding_code": "test_story_required",
      "classification": "semantic",
      "action_kind": "inspect_story_candidate",
      "sort_key": [1, "test_case", "TC-0001", "inspect_story_candidate", "test_story_required"],
      "entity": {"type": "test_case", "id": "TC-0001"},
      "related": [{"type": "user_story", "id": "US-0001"}],
      "safe_to_apply": false,
      "requires_human": true,
      "command": "pcl story read US-0001 --json",
      "reason": "A Story link requires an explicit operator choice."
    }
  ]
}
```

`classification` is a closed public enum with exactly `structural`, `semantic`,
`human_review`, and `unsupported`. `summary` contains exactly those four count
keys, including zero values. `action_kind` is a stable public snake-case action
identifier such as `add_missing_evidence_link`, `inspect_story_candidate`, or
`record_goal_verification`; consumers must not infer it from prose.

Every action publishes its canonical `sort_key` array:

```text
[classification_rank, entity.type, entity.id, action_kind, finding_code]
```

The fixed ranks are structural=0, semantic=1, human_review=2, unsupported=3.
Actions are sorted lexicographically by this array before sequential
`LR-0001` IDs are assigned. IDs are deterministic within the plan and are not
persisted domain IDs. An action with no primary entity uses empty strings for
both entity sort components. Text output uses the same order and four labels.

## Structural versus semantic boundary

An action is structural only when all source and target IDs already exist and
the relationship is unambiguous from authoritative stored data. Initial
supported examples are:

- restore a missing `test_case` / `acceptance` `evidence_links` row when the
  terminal Test already stores that same healthy `evidence_id`;
- restore a missing completion-packet link when the validated packet itself is
  targeted to the same entity and no conflicting target/link exists.

The following are always plan-only semantic or human actions, even when only
one candidate appears to exist:

- approve, review, or waive a Story;
- choose or change a Test-to-Story relationship;
- choose, create, copy, or replace Evidence;
- change a lifecycle status;
- record or approve a Verification;
- close or reopen a Goal, Feature, Test, Decision, or Escalation;
- choose between conflicting candidates or reinterpret legacy inline text.

An exactly-one Story heuristic is therefore not sufficient for automatic
linking or approval. Unsupported corruption is reported, not normalized.

## Scope

- Add `src/pcl/lifecycle_repair.py` and the `pcl repair lifecycle` parser and
  dispatch path.
- Reuse lifecycle predicates from `src/pcl/validators.py`; do not parse legacy
  validation message strings to discover entities.
- Add synthetic existing-project fixtures and
  `tests/test_lifecycle_repair.py`.
- Extend `docs/recovery-playbook.md` with the plan-first migration path.

## Invariants

- Default and dry-run modes cause zero mutation, including no projector flush
  or generated report.
- Semantic actions are never auto-executed, auto-approved, or converted to a
  structural action by candidate count.
- 0142 does not add an apply flag, internal link mutation service, transaction,
  event, or post-repair validation path.
- No raw SQL or generated HTML becomes an operator repair interface.
- Existing validation severity policy, same-status no-op behavior, CLI flags,
  and JSON fields remain backward compatible.
- No migration, dependency, LLM call, agent launch, or remote operation.

## Non-goals

- Generic database repair or audit-log rebuild (covered by 0129).
- Any repair application, including unambiguous structural link mutation.
- Internal/common link mutation services and dedicated link commands; these
  belong to 0143.
- Post-repair strict-pass orchestration or acceptance; this belongs to 0143.
- Automatic application of suggested shell commands.
- Schema-backed generic Verification targets.
- Enabling enforced lifecycle policy for unrepaired existing projects.

## Acceptance criteria

- Bare and explicit dry-run produce the same deterministic plan and leave DB,
  event/outbox/JSONL, report, dashboard, and Evidence hashes unchanged.
- A passing Test with no Story remains a semantic operator action; an
  exactly-one candidate is not linked or approved.
- A missing link derivable from an existing healthy `test_cases.evidence_id`
  is classified structural and described with a stable `action_kind`, but is
  not applied.
- Conflicting, missing, drifted, cross-target, or wrong-role Evidence is not
  auto-repaired.
- `classification` rejects values outside the fixed four-value enum; summary
  always contains exactly the four classification keys.
- The published sort key, fixed ranks, `action_kind`, and post-sort action IDs
  produce identical output for identical state.
- Text and JSON output contain the same action classes and concrete IDs; stdout
  remains pure JSON in JSON mode.
- Targeted tests, full `pytest`, `ruff check .`, strict validation, and render
  pass in an initialized verification project.

## Evidence required to close

- Before/after hashes and row/event counts proving dry-run zero mutation.
- JSON fixtures for all four classifications, public action kinds, canonical
  sort keys, zero-filled summary keys, ambiguous cases, and idempotent reruns.
