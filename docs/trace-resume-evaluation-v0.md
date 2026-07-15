# Trace Resume Evaluation v0

This document freezes the controlled dogfood contract for v0.5.1 Trace &
Efficient Handoff. It measures whether a new session can resume useful work
from a small claim-bound packet while preserving source and trust boundaries.
It is not evidence that a model understood a full transcript.

The machine-readable fixture is
`tests/fixtures/trace_binding_v0/trace-resume-evaluation-fixture.json`.
Task 0178 freezes the format; Task 0181 records real results.

Task 0181 preparation is recorded in
`docs/evaluation/v0.5.1-trace-resume-cohort.json` and the matching runbook. The
prepared packets are not results: model/provider authorization remains false
until a human explicitly scopes the independent consumer runs.

The first frozen run, `TRC-20260715-01`, is recorded in
`docs/evaluation/v0.5.1-trace-resume-results.json`. It passed broken-binding
safe-stop and no-index compatibility, but failed valid resume and critical
trust-boundary thresholds. The recorded recommendation is `modify`; the failed
cases remain in the denominator and the RC stays blocked pending human review.

## Cohort

The minimum controlled cohort contains:

- 10 handoff cases across at least two owned repositories;
- at least two distinct resume sessions;
- at least four cases where runtime or model differs between source and resume;
- valid bindings plus deliberately broken hash, Evidence, path, and line-range
  bindings.

Provider-backed cross-model runs occur only when the operator has separately
authorized their cost and credentials. Owned-repository same-provider cases can
continue meanwhile, so unavailable external users do not block the milestone.

## Case contract

Each case records a stable ID, repository slot, source/resume session IDs,
source/resume runtime and model labels, binding mode, and expected outcome.
Runtime/model labels are descriptive cohort dimensions, not identity or quality
claims. Broken bindings must expect `safe_stop`; valid bindings expect
`resume`.

## Result contract

Each result records:

- case and run identity;
- handoff packet bytes and full trace bytes;
- selected claim-ref count;
- outcome: `resumed`, `assisted`, `safe_stop`, or `failed`;
- success and assistance-required booleans;
- whether safe stop was required and observed;
- whether referenced source lines were checked;
- whether any model claim was treated as verified;
- critical trust-boundary violation status;
- replayable verification commands and notes.

`safe_stop_observed` is nullable only when safe stop was not required. Notes are
context, not a substitute for the structured fields. Fixture examples are not
dogfood results.

## Promotion thresholds

The controlled cohort passes when:

- resume success is at least 80% for eligible valid-binding cases;
- broken bindings safe-stop at 100%;
- critical trust-boundary violations are zero.

Assisted outcomes remain visible rather than being silently counted as
unassisted success. Byte sizes are retained so a useful resume can be compared
with the full trace instead of assuming the handoff is efficient.
