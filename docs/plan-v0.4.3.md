# v0.4.3 Evidence Completeness plan

**Status:** Local v0.4.3 release candidate prepared through 0153b; not published
**Source evidence:** `docs/dogfood/lp-production-cross-skill-review.md`
**Project Loop:** F-0022 / US-0020 / TC-0039
**Release boundary:** starts after the frozen v0.4.2 local RC; it does not
change the v0.4.2 artifacts, hashes, or release note.

## Goal

Make Project Loop terminal state mean that the declared evidence set is
complete for the target—not merely that an agent selected one passing report.
Cross-skill results such as `prototype` and `complete` map to PCL state by an
explicit, deterministic, domain-neutral policy.

## Invariants

- SQLite and generated dashboard files remain service-owned.
- Every mutation appends an event; existing hash-pinned Evidence is immutable.
- Required evidence is target-bound; sibling files are not authoritative only
  because they exist.
- Discovery is constrained to an explicit work root and report manifest. PCL
  does not scan arbitrary parent directories.
- External verdict evaluation is deterministic, local, JSON-based, and
  dependency-light. Core does not call an LLM.
- Human approval stays human-gated. Agent self-review cannot manufacture human
  provenance.
- Existing projects receive an advisory compatibility path before new
  planning-time enforcement.
- Schema remains 8. If implementation requires a migration, stop at the
  migration decision and obtain human approval.

## Canonical dispatch

| Order | Task | Outcome |
|---|---|---|
| 1 | 0150 Evidence-set completeness contract | A target-bound manifest describes included, required, and known-excluded reports; incomplete required sets fail closed. |
| 2 | 0151 Completion-policy adapter and terminal preflight | Generic JSON predicates bind external verdicts and structured acceptance conditions to Test terminal transitions. |
| 3 | 0152 Next-action and approval-provenance integrity | Passing-but-not-done work remains actionable; approval receipts distinguish human, agent, and system actors. |
| 4 | 0153 Cross-skill dogfood, Skill/CLI parity, and release gate | False-completion fixture is rejected, complete fixture passes, docs use Evidence-ID-first commands, and human review gates release. |
| 5 | 0153b Local release preparation | Version surfaces, release notes, final checks, fresh artifacts, clean-wheel smoke, and hashes are prepared without publication. |

The slices are serialized because they overlap terminal guards, validators,
next-action routing, Evidence contracts, Skill copies, and fixtures.

## Acceptance model

### Evidence-set completeness

The contract records target type/id, explicit work root and report manifest,
included Evidence IDs and roles, required report kinds, known exclusions with
factual reasons, and a deterministic completeness assessment. A bundle cannot
be presented as complete when a declared required or known-failing report is
absent. Discovery warnings are informational unless target policy marks the
report required or blocking.

### External completion policy

The adapter evaluates declared JSON fields with a small allowlisted predicate
set: equality, membership, numeric threshold, required path, and empty finding
list. It does not execute arbitrary code or infer semantics from prose.

- `prototype` may be recorded honestly as an intermediate result.
- A Test requiring `complete` cannot pass with `prototype` or a missing verdict.
- A complete verdict is insufficient if required failures remain unresolved.
- Test `passing` means acceptance checks passed; Feature `done` remains an
  explicit lifecycle decision.

### Approval provenance

Receipts expose at least `actor_kind` (`human`, `agent`, or `system`), factual
actor identity when available, source command/event, timestamp, target, and
bound Evidence hash. Only explicit human-origin actions satisfy human approval.

## Compatibility and CLI policy

- `--evidence-id` is the canonical terminal-proof interface in bundled Skill
  and operator docs.
- Raw `--evidence` remains a caller claim for compatibility, but documentation
  must not imply equivalent durable proof.
- Under enforced lifecycle policy, `pcl test plan` without `--story` fails
  before mutation. Advisory projects get a structured warning and link command.
- JSON output changes are additive unless the stability gate approves otherwise.

## Verification matrix

| Fixture | Required result |
|---|---|
| Positive reports selected, known 35.3% failure excluded | terminal pass rejected with zero Test/Feature/event traces |
| Verdict is `prototype`, policy requires `complete` | pass rejected; next action identifies missing completion |
| Verdict is `complete`, all required reports included and passing | Test may pass with hash-pinned Evidence |
| Feature is `passing` but not `done` | `pcl next --json` is actionable, not idle |
| Agent self-review exists, human approval required | approval gate remains unresolved |
| Test planning omits Story under enforced policy | rejected before mutation |
| Equivalent commands in all bundled Skill copies | parser and golden-output tests pass |

## Success metrics

- zero accepted false-completion transitions in canonical cross-skill fixtures;
- 100% of required external reports represented in evidence-set receipts;
- zero idle routes for `passing` but unfinished Features;
- 100% of human-gated approvals carry human provenance;
- no regression in legacy advisory projects or JSON/text determinism;
- strict validation, full pytest, package checks, and clean-install smoke pass
  before a v0.4.3 local RC.

## Non-goals

- motion, crop generation, typography extraction, or line detection in PCL;
- global scanning for guessed negative evidence;
- executing third-party code from a completion policy;
- hosted coordination, telemetry, marketplace publication, or cloud sync;
- publishing v0.4.2 or v0.4.3 without separate explicit operator action.

## Human gates

1. Approve this plan and US-0020 before implementation starts.
2. Approve any schema migration if schema-8 receipts prove insufficient.
3. Independently review cross-skill dogfood before release preparation.
4. Treat tag, push, GitHub Release, and PyPI as separate explicit operations.
