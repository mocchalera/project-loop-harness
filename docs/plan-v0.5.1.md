# v0.5.1 Trace & Efficient Handoff plan

- **Status:** Published and independently verified
- **Decision date:** 2026-07-15
- **Decision source:** Cockpit Ask `ask_8f99470fc206`
- **Schema baseline:** 8; no migration is assumed

## Decision

Project Loop Harness will not wait for three external users before starting the
v0.5.1 Trace milestone. The prepared three-person first-use study remains useful
future Adoption evidence, but participant availability is not a release-planning
dependency.

v0.5.1 will instead use controlled, operator-led dogfood across independent
sessions and owned repositories. External-user evidence may revise priorities
when it arrives, but absence of that evidence must not be presented as product
adoption or market validation.

## Current baseline

The repository already implements more than the original M6 proposal assumed:

- `master-trace/v0` and `intent-index/v0` are documented Evidence contracts;
- `pcl context check` and opt-in `master_trace_context` resolve linked artifacts;
- `pcl resume` references trace/index Evidence without inlining full transcripts;
- no-index projects retain the existing handoff path.

The remaining gap is narrower and measurable. Current preflight recognizes
contract markers and copied paths, but it does not prove that an index's
`source_trace` matches the recorded Evidence manifest and hash, that every
source range resolves inside the copied trace, or that a receiving session can
reliably continue from selected claim references.

## Goal

Prove that an independent session or agent runtime can resume useful work from
a small, claim-bound handoff without receiving the full transcript, while PLH
keeps every model-produced index item explicitly unverified until a consumer
checks its copied source lines.

## Exit conditions

v0.5.1 is ready for a local release candidate only when all conditions below
are evidenced:

1. `intent-index/v0` structure, Evidence identity, copied path, SHA-256, and
   one-based inclusive line ranges are checked deterministically.
2. Broken hashes, mismatched Evidence IDs or paths, out-of-range lines,
   unsupported contracts, duplicate item IDs, and empty source refs fail with
   stable typed diagnostics and no state mutation.
3. Valid handoffs expose bounded claim references as **unverified claims** with
   deterministic ordering and omission reasons; they never inline transcript
   text or promote index wording into `verified` facts.
4. Projects without a trace/index retain compatible `context pack` and
   `pcl resume` behavior.
5. A frozen controlled evaluation covers at least 10 handoffs across at least
   two owned repositories and two independent sessions. At least four cases
   must cross an agent-runtime or model boundary when that execution has the
   required authorization.
6. At least 80% of frozen cases reach their defined next-step outcome without
   the full transcript or extra operator explanation. All intentionally broken
   binding cases must stop safely, and critical trust-boundary violations must
   remain zero.
7. The evaluation reports packet bytes, source-trace bytes, omitted claims,
   source-resolution failures, assistance required, and check results without
   treating those observations as telemetry or broad adoption evidence.
8. Targeted tests, full lint and test, strict validation, source/wheel/sdist
   contract checks, and clean-install smoke pass before the RC is presented.

## Measurement definitions

`resume_success` means that the receiving session uses only the handoff packet,
its referenced copied artifacts, and repository state to identify and complete
the frozen next step. The result must satisfy the case's deterministic check or
its predeclared human-review rubric. Opening the referenced copied source lines
is allowed; receiving the full transcript inline or an extra explanation from
the originating session is not.

A source-binding safe stop is successful only when the invalid condition is
reported before claim selection or recommendation. PLH does not judge whether a
claim semantically summarizes the source correctly; that remains a consumer
review responsibility.

## Milestones and dispatch

1. **0178 — Contract and fixture freeze.** Characterize current behavior and
   freeze the additive claim-reference and evaluation contracts.
2. **0179 — Source-binding validation.** Add deterministic structural and
   Evidence/line-range checks to existing read-only surfaces.
3. **0180 — Claim-bound handoff.** Add bounded unverified claim references,
   deterministic selection, and omission metadata to context/resume output.
4. **0181 — Controlled resume evaluation.** Run the frozen two-repository,
   cross-session/runtime dogfood and record the milestone decision.
5. **0182 — Local RC.** Align release surfaces and verify source, wheel, sdist,
   and clean-install behavior.
6. **Human publication decision.** No tag, push, GitHub Release, or PyPI write
   occurs without a separate explicit decision.
7. **0183 — Publication closeout.** After authorized publication, independently
   verify the immutable public chain and synchronize factual release docs.

Implementation is serialized through 0180 because the contracts, validator,
context selector, resume schema, and fixtures overlap. 0181 may not weaken an
acceptance threshold after seeing results; any threshold change requires a new
recorded decision and rerun.

## Invariants

- PLH Core does not call an LLM or capture transcripts automatically.
- `intent-index/v0` remains model-produced claims, not a new source of truth.
- No first-class Trace, Intent, Collection, Option, or Knowledge table is added.
- Context and resume inspection stay read-only.
- SQLite and the event/audit model remain authoritative for PLH state.
- No hosted backend, cloud sync, telemetry, semantic embedding search, or
  default Council activation is included.
- A schema migration, dependency addition, paid/network model run, external
  publication, or destructive operation requires its own human approval.

## External-user study disposition

The three-person study in `docs/launch/v0.5.0/feedback-study.md` remains a valid
protocol for later market-facing evidence. It is not cancelled and it is not a
v0.5.1 blocker. When participants become available, their observations enter a
separate Adoption review and may produce follow-up work without retroactively
turning controlled dogfood into external-user evidence.

## Controlled evaluation decision

The first frozen cohort failed and remained in the denominator. After the human
selected `Modifyして全件再実行`, cohort `TRC-20260715-02` fixed authorization
precedence before freeze and used representative traces longer than every
packet. Codex and Claude completed all ten cases: valid resume 6/6, broken
binding safe-stop 4/4, critical trust-boundary violations 0, and no-index
compatibility 2/2. The human reviewed Evidence `E-0432` and `E-0433` in
`ask_6d59ffeb5ebf` and selected `Continue`.

This satisfies the controlled-evaluation gate for local RC preparation. It does
not claim external adoption and does not authorize tag, push, GitHub Release,
PyPI publication, pipx upgrade, or launch announcement.
