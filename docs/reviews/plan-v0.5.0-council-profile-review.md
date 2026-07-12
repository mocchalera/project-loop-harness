# v0.5.0 Council Profile plan quality review

**Reviewed document:** `docs/plan-v0.5.0-council-profile.md`
**Review date:** 2026-07-12
**Branch/baseline:** `main` at `0eb3273`
**Rubric:** update-design 100-point scoring rubric
**Independent review:** Claude Fable Cockpit task `672a9fc3`

## Evaluation summary

The original self-review moved from 96/100 to 100/100 after adding the first
authorization, durability, risk, and maintenance details. Claude Fable then
performed an independent code-grounded review and invalidated that score. The
pre-amendment plan scored **82/100** and was not shippable because it contained
three P1 defects:

1. volatile context receipt-age fields made authorization basis digests stale;
2. legacy Decision resolve/waive could bypass proposal provenance;
3. the existing audit implementation could not detect Profile bundle orphans.

The review also found an incorrect `/tmp` Evidence claim, ambiguous v0.5.0
release scope, overloaded Profile terminology, an omitted authorize CLI entry,
undefined project fingerprint and claim promotion boundaries, and an
unexecutable schema-meta-validation promise.

All required findings were converted to plan/task changes. The revised plan
scores **100/100**. This assesses planning completeness only; implementation,
ADR acceptance, and release approval remain open.

## Final score

| Area | Score | Evidence |
|---|---:|---|
| Purpose and success conditions | 15/15 | Outcome flow, separate feature/release tracks, Definition of Done |
| Scope boundaries | 10/10 | Core/external/non-goal and Council/Adoption separation |
| Assumptions, constraints, dependencies | 10/10 | Basis normalization, project fingerprint, gates, task graph |
| Functional specificity | 15/15 | Complete CLI, authorization, bypass guard, ingest and status semantics |
| Non-functional requirements | 10/10 | Time determinism, zero mutation, audit orphan recovery, security |
| Data/API/interface consistency | 10/10 | Seven contracts, claim-to-proof mapping, terminology, Evidence/events |
| Task decomposition and executability | 10/10 | Findings propagated to 0154/0155/0156/0158/0159/0160 |
| Test and acceptance strategy | 10/10 | Time, bypass, orphan, package, compatibility and full-suite gates |
| Risks, alternatives, rollback | 5/5 | Risk register, built-in-only decision, rollback and audit guidance |
| Operations, migration, maintenance | 5/5 | Separate release-readiness track, contract lifecycle and human gates |
| **Total** | **100/100** | No fatal omission remains |

## Improvement tasks completed

| Priority | Task | Completion condition | Impact | Owner |
|---|---|---|---|---|
| P0 | Stabilize authorization basis | Exact time-field exclusions; cross-time identical basis for unchanged state | Contracts, prepare, authorize | 0154/0156/0159 |
| P0 | Close legacy Decision bypass | Proposal-linked plain resolve/waive returns typed zero-mutation error | Decision CLI and E2E | 0159/0160 |
| P0 | Add Profile orphan audit | Finalized unreferenced bundle directory is detected and reported | Evidence durability/audit | 0158 |
| P1 | Correct Evidence-source claim | Dedicated bundle path justified by atomic directory semantics, not false `/tmp` rejection | Plan and 0158 | Plan owner/0158 |
| P1 | Separate release tracks | Council Feature DoD and Adoption/Distribution publication gate are explicit | Roadmap/indexes | Plan owner |
| P1 | Complete interface contract | `pcl profile authorize`, Profile terminology, project fingerprint and claim mapping are explicit | 0154–0156 | Plan owner/implementers |
| P1 | Remove dependency ambiguity | Schema proposal validation does not imply an unapproved jsonschema dependency | 0154 | 0154 implementer |

## Revision summary

- Defined exact request-basis exclusions for generated time, `receipt_age`, and
  `age_warning`, while preserving receipt timestamps, source refs, and hashes.
- Defined a local project fingerprint whose absolute root participates only in
  a digest and never appears in the request.
- Added `pcl profile authorize` to the canonical CLI list.
- Required legacy resolve/waive to reject proposal-linked Decisions with
  `decision_proposal_command_required` while preserving ordinary behavior.
- Added Profile bundle orphan detection explicitly to 0158 and audit recovery.
- Corrected outside-root Evidence behavior and retained a separate staging path
  for directory atomicity, re-hash, and immutability.
- Defined claim-set to Evidence/Verification/Decision/Work Brief/completion
  boundaries with no automatic proof promotion.
- Kept `pcl profile`, with distinct `route_profile`, `runner_profile_id`, and
  `role_profile` public vocabulary.
- Split Council 0154–0162 from a separately numbered Adoption/Distribution
  release-readiness track; both must close before publication.
- Reworded 0154 schema acceptance so it adds no runtime or dev dependency.

## Final consistency check

- **Contradictions:** none found. Proposal-linked Decisions have one
  provenance-bound close path; ordinary Decision compatibility remains.
- **Coverage gaps:** none found across purpose, constraints, CLI, contracts,
  persistence, security, tasks, tests, audit, rollback, and release scope.
- **Terminology:** route profile, runner Profile ID, and role profile are
  explicitly distinct; the public command remains `pcl profile` by human
  decision.
- **Unresolved items:** ADR-005 acceptance, external runner repository, real
  paid/network dogfood, any migration, 0162 adoption, separate
  Adoption/Distribution task numbering, and publication remain intentional
  human gates with trigger conditions.
- **Implementation status:** not started. The safe next action is task 0154's
  ADR/proposal contract freeze after this amended plan passes verification.

