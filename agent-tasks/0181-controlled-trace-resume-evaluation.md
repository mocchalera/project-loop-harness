# 0181: Controlled Trace resume evaluation

- **Status:** Done
- **Milestone:** v0.5.1 Trace & Efficient Handoff
- **Priority:** P0
- **Size:** M
- **Dependency:** 0180 claim-bound context and resume handoff
- **DB schema:** remains 8

## Goal

Measure whether independent sessions can continue useful work from the
claim-bound handoff without waiting for external users and without weakening
the claims-not-facts boundary after results are known.

## Scope

1. Freeze at least 10 evaluation cases before execution across this repository
   and at least one other owner-controlled repository.
2. Use at least two independent sessions; at least four cases cross a different
   agent runtime or model when separately authorized.
3. Give the consumer only the handoff packet, its referenced copied artifacts,
   and repository state; do not provide the full transcript or extra origin
   explanation.
4. Record next-step outcome, assistance, source-ref resolution, omissions,
   packet/trace bytes, checks, and trust-boundary violations.
5. Include intentionally broken binding cases and no-index compatibility cases.
6. Produce a predeclared continue/modify/stop milestone result.

## Invariants

- No external participant is required.
- No telemetry or automatic external upload.
- A network/paid/model-provider run requires explicit authorization naming its
  scope, data class, budget, and expiry.
- Failed cases and safe stops stay in the denominator.
- Thresholds are not changed after observing results without a new decision and
  complete rerun.

## Acceptance

1. At least 10 frozen cases and two repositories are represented.
2. Resume success is at least 80% under the definition in
   `docs/plan-v0.5.1.md`.
3. Every intentionally broken binding stops before claim use.
4. Critical trust-boundary violations are zero.
5. Full transcript content is absent from every packet.
6. The report includes all failures, assistance, limitations, and size ratios
   and does not claim external adoption.
7. A human reviews the evidence and records continue, modify, or stop before RC.

## Non-goals

- Recruiting three first-use participants.
- Market validation or a public benchmark claim.
- Real-provider Council activation.

## Preparation checkpoint

- Frozen cohort: `docs/evaluation/v0.5.1-trace-resume-cohort.json`
- Independent execution runbook:
  `docs/evaluation/v0.5.1-trace-resume-runbook.md`
- Ten hash-bound `pcl resume` packets plus one no-index compatibility packet:
  `docs/evaluation/v0.5.1-trace-resume-packets/`
- PCL case tasks: `T-0077` through `T-0086`
- Trace/index Evidence: `E-0409` through `E-0416`
- At this checkpoint independent execution was pending explicit scope, data,
  budget, and expiry authorization; the later authorization and run are
  recorded separately below.

## First frozen run result

- Cohort `TRC-20260715-01` executed after human authorization `E-0419`.
- Codex completed one valid resume and all four expected broken-binding safe
  stops.
- Claude stopped before its five valid cases after reading forbidden
  runbook/cohort/authorization context and finding ambiguous authorization
  precedence.
- Valid resume: 1/6 (16.67%); broken safe-stop: 4/4 (100%); critical
  trust-boundary violations: 5 contaminated cases.
- All packet/trace byte ratios exceeded 1, so the run does not demonstrate
  byte-size efficiency.
- Machine recommendation: `modify`; human continue/modify/stop decision is
  still required before RC.
- Results: `docs/evaluation/v0.5.1-trace-resume-results.json`
- Evidence report: `docs/evidence/0181-controlled-trace-resume-evaluation.md`

## Modified full rerun result

- Human selected `Modifyして全件再実行` in `ask_8dd6e7bb58a5`.
- Authorization `E-0422` was fixed before the new cohort
  `TRC-20260715-02`; its precedence is explicit and authoritative.
- Ten new hash-bound packets use representative copied traces longer than each
  packet. Codex and Claude each consumed five cases.
- Valid resume: 6/6 (100%); broken safe-stop: 4/4 (100%); critical
  trust-boundary violations: 0; no-index compatibility: 2/2.
- Packet/Trace ratios are 0.344158 through 0.531553.
- Machine recommendation: `continue`; human review is still required before RC.
- Aggregate: `docs/evaluation/v0.5.1-trace-resume-results-02.json`
- Evidence report:
  `docs/evidence/0181-controlled-trace-resume-evaluation-rerun.md`
- Human reviewed `E-0432` and `E-0433` in `ask_6d59ffeb5ebf` and selected
  `Continue`; the decision receipt is
  `docs/evaluation/v0.5.1-trace-resume-human-decision-02.json`.
