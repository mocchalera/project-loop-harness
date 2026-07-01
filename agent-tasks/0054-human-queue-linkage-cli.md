# Task 0054: Human Queue Linkage CLI

## Goal

Expose escalation/decision linkage directly from human queue CLI reads.

Dogfooding feature coverage for `F-0010` showed that dashboard, reports, and
`pcl next` expose linked decisions/escalations, but `pcl decision read/list` and
`pcl escalation read/list` did not show those derived link fields.

## Scope

- Add `linked_escalation_ids` to decision read/list JSON rows.
- Add `linked_decision_ids` to escalation read/list JSON rows.
- Derive links from existing `decisions.blocks_json`.
- Reuse existing link helpers.
- Add CLI regression tests for linked and unlinked queue rows.

## Acceptance Criteria

- `pytest tests/test_decisions.py tests/test_escalations.py` passes.
- Full `pytest` passes.
- `pcl validate --strict --json` passes.
- No schema migration is added.

## Do Not

- Do not add new tables or columns.
- Do not change dashboard/report link derivation.
- Do not auto-resolve decisions or escalations.
- Do not add external notifications.
