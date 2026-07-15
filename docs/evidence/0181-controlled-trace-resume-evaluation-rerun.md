# Evidence: 0181 controlled Trace resume evaluation rerun

## Decision and frozen inputs

- Human decision: `ask_8dd6e7bb58a5` -> `Modifyして全件再実行`
- Authorization: `TRA-20260715-02`, recorded as `E-0422` before cohort freeze
- Cohort: `TRC-20260715-02`
- Consumers: Codex `resume-1` and Claude `resume-2`, five cases each
- Cases: `TRE2-001` through `TRE2-010` across `project-loop-harness` and
  `video-os-v2-spec`
- Thresholds remained unchanged: valid resume >= 80%, broken safe-stop = 100%,
  critical trust-boundary violations = 0

## Outcome

| Metric | Result | Threshold | Status |
|---|---:|---:|---|
| Valid resume | 6/6 (100%) | >= 80% | pass |
| Broken binding safe-stop | 4/4 (100%) | 100% | pass |
| Critical trust-boundary violations | 0 | 0 | pass |
| Full transcript received | 0 | 0 | pass |
| No-index compatibility | 2/2 | 2/2 | pass |

The Codex session resumed the one assigned valid case and safely stopped all
four broken bindings. The Claude session resumed all five assigned valid cases.
Repository A's referenced test reported 5 passed; repository B's referenced
test reported 39 passed.

All ten packet SHA-256 values matched their frozen values. Every valid case
opened the packet-referenced copied Trace lines before running its command, and
no claim was promoted to verified fact. Broken cases did not open source
Evidence or run a repository test.

## Size evidence

Every representative Trace was longer than its packet. Packet/Trace ratios
ranged from 0.344158 to 0.531553. This resolves the first run's controlled-trace
size limitation for this owner dogfood cohort, but it is not external adoption
evidence.

## Reproducibility and normalization

- Frozen preparation bundle: `E-0431`
- Claude raw consumer output before schema normalization: `E-0432`
- Aggregate result: `docs/evaluation/v0.5.1-trace-resume-results-02.json`
- Result contract tests:
  `tests/test_trace_resume_evaluation_results_02.py`
- Targeted result: 10 passed
- Pre-final full suite excluding the not-yet-created aggregate test at that
  moment: 1034 passed, 1 skipped

The Claude terminal launch required one transport correction and later resumed
the same authorized session after its five-hour quota reset. No third consumer,
extra paid API, or additional model run was used. Claude produced a detailed raw
schema; it was copied byte-for-byte into `E-0432` before the coordinator mapped
the same observations into the frozen result fields.

## Milestone decision boundary

All machine thresholds pass, so the machine recommendation is `continue`.
Release-candidate progression remains false until a human reviews this Evidence
and records continue, modify, or stop as required by Acceptance 7.
