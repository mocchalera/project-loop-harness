# agent-tasks

Spec-first backlog and design history for Project Loop Harness.

Each file is one task spec: problem, scope, invariants ("what to protect",
stated against the normal paths), non-scope, and acceptance criteria. Specs
are committed to `main` **before** any worker starts implementing — workers
implement from the spec file, not from prompt summaries.

- **Canonical ordered index (all tasks, oldest first):** [`../TASKS.md`](../TASKS.md)
- **Roadmap and milestone rationale:** [`../docs/growth-plan-v0.2.4-v0.5.md`](../docs/growth-plan-v0.2.4-v0.5.md)

## Active backlog

| ID | Title | Milestone | Priority | Status |
|---|---|---|---|---|
| 0102 | Source drift health warning | v0.2.4 Trust Patch | P1 | done |
| 0103 | SECURITY.md v0.2.x + copied-evidence policy | v0.2.4 Trust Patch | P1 | done |
| 0104 | Python 3.10–3.13 CI matrix | v0.2.4 Trust Patch | P2 | done |
| 0105 | Evidence copy observability | v0.2.4 Trust Patch | P2 | done |
| 0106 | Release checklist contract | v0.2.4 Trust Patch | P2 | done (`docs/release-checklist.md`) |
| 0107 | agent-tasks backlog index | v0.2.4 Trust Patch | P3 | done (this file) |
| 0113 | Generic evidence_links table (migration 007) | v0.3.0 Target-Bound Context | P1 | done (shipped v0.3.0) |
| 0108 | Target-bound code context receipts (sits on 0113) | v0.3.0 Target-Bound Context | P1 | done (shipped v0.3.0) |
| 0114 | Source hash drift detection (default-on) | v0.3.0 Target-Bound Context | P2 | done (shipped v0.3.0) |
| 0115 | Context pack target-bound contract fixtures | v0.3.0 Target-Bound Context | P2 | done (shipped v0.3.0) |
| 0116 | Target-bound receipt / link agreement validation | v0.3.1 Handoff Integrity | P1 | done (shipped v0.3.1) |
| 0117 | Target-specific refresh command in code-context Markdown | v0.3.1 Handoff Integrity | P1 | done (shipped v0.3.1) |
| 0118 | Canonical target-bound handoff docs (README + adoption) | v0.3.1 Operator Experience | P1 | done (shipped v0.3.1) |
| 0119 | `pcl context check` read-only preflight | v0.3.1 Operator Experience | P1 | done (shipped v0.3.1) |
| 0120 | `pcl finish` terminal close-out planner (F7) | v0.3.1 Operator Experience | P1 | done (shipped v0.3.1) |
| 0121 | Japanese human-gate guidance in `pcl next` (F5) | v0.3.1 Operator Experience | P1 | done (shipped v0.3.1) |
| 0122 | feature_coverage no-op when all covered (F4) | v0.3.1 Operator Experience | P1 | done (shipped v0.3.1) |
| 0123 | Master trace / intent-index v0 contract formalization | v0.3.2 Master Trace / Intent Index | P1 | done (main 3821e7a; contract accepted DEC-0002) |
| 0124 | Freeze v0.3.1 baseline (snapshot fixtures + baseline doc) | v0.3.3 Trust Foundation (Wave A) | P0 | done (main c9ebd32) |
| 0125 | MCP stdio framing + version negotiation spec compliance | v0.3.3 Trust Foundation (Wave A) | P0 | done (main 6997dfc) |
| 0126 | MCP external conformance fixtures + compatibility matrix | v0.3.3 Trust Foundation (Wave A) | P0 | done (main 9874c05; pre-init lifecycle follow-up fdc0f7f) |
| 0127 | Transactional audit outbox ADR + failure model | v0.3.3 Trust Foundation (Wave A) | P0 | done (main 29c995a; ADR-002 Accepted DEC-0001) |
| 0128 | Event outbox + idempotent JSONL projector | v0.3.3 Trust Foundation (Wave A) | P0 | done (main 4e7ff99) |
| 0129 | Audit check / repair / rebuild (extends validate --strict integrity check) | v0.3.3 Trust Foundation (Wave A) | P0 | done (main c150879) |
| 0130 | Crash injection + concurrent writer suite | v0.3.3 Trust Foundation (Wave A) | P0 | done (main cee0026) |
| 0131 | Guarded executor hardening (terminology, caps, redaction) | v0.3.3 Trust Foundation (Wave A) | P1 | done (main cdbcf3a) |
| 0132 | Optional master_trace_context section in context-pack/v1 | v0.3.2 Master Trace / Intent Index | P1 | done (main a2a09d9) |
| 0133 | Windows advisory-lock fallback (msvcrt) | v0.3.3 Trust Foundation (release blocker) | P0 | done (main 6a3212a; shipped v0.3.3) |
| 0134 | completion-packet/v1 contract | v0.4.0 Three-command Wedge | P0 | done (main e801ef0) |
| 0135 | `pcl finish` completion packet emission | v0.4.0 Three-command Wedge | P0 | done (main 84be7a0) |
| 0136 | Lite `pcl start` | v0.4.0 Three-command Wedge | P0 | done (main 4272ab0) |
| 0137 | handoff-packet/v1 and read-only `pcl resume` | v0.4.0 Three-command Wedge | P0 | done (main 34ac60c) |
| 0138 | `pcl report kpi` surface | v0.4.0 Dogfood Operations | P1 | done (main 6f1c024) |
| 0139 | Executable restart context repair | v0.4.0 Three-command Wedge | P0 | done (main bcb6cf5) |
| 0140 | KPI post-integration data sources | v0.4.0 release candidate | P0 | done (main 9d2ff23) |
| 0140a | Skill / CLI contract parity | v0.4.0 RC2 Integrity Gate | P0 | done (main 8bd6aa3) |
| 0140b | Evidence-backed lifecycle integrity gate | v0.4.0 RC2 Integrity Gate | P0 | done (main ad082d7 + d5d2602) |
| 0140c | Fail-open finish check guard | v0.4.0 RC2 Integrity Gate | P0 | done (main 131d9d4) |
| 0141 | Idle routing without a redundant human gate | v0.4.1 Integrity Migration | P0 | done (main ce3dcd0) |
| 0142 | Plan-only lifecycle repair action model | v0.4.1 Integrity Migration | P1 | done (main 3338d5f) |
| 0143 | Terminal link mutation and structural repair apply | v0.4.1 Integrity Migration | P1 | done (main 11f8e03) |
| 0144 | Schema-8 artifact/event-anchored Skill provenance | v0.4.1 Integrity Migration | P1 | done (main 20f117b) |
| 0145 | Structured validation diagnostics and repair guidance | v0.4.1 Integrity Migration | P1 | done (main f447f8a) |
| 0145a | Released-v0.3.0 integrity migration dogfood | v0.4.1 Integrity Migration | P1 | done (main 1063d62) |
| 0145b | v0.4.1 local release preparation | v0.4.1 Integrity Migration | P0 | done (local release commit) |
| 0146 | Immutable Work Brief Evidence contract | v0.4.2 Adaptive Entry | P0 | done (human-approved) |
| 0147 | Deterministic route recommendation | v0.4.2 Adaptive Entry | P0 | done (human-approved) |
| 0148 | Adaptive policy resolve and explain | v0.4.2 Adaptive Entry | P0 | done (human-approved) |
| 0149 | Audited override and packet integration | v0.4.2 Adaptive Entry | P0 | done (human-approved) |
| 0149a | Two-repository Adaptive Entry dogfood | v0.4.2 Adaptive Entry | P0 | done (human-reviewed) |
| 0149b | v0.4.2 local release preparation | v0.4.2 Adaptive Entry | P0 | done (local RC; not published) |
| 0150 | Evidence-set completeness contract | v0.4.3 Evidence Completeness | P0 | done (local RC) |
| 0151 | Completion-policy adapter and terminal preflight | v0.4.3 Evidence Completeness | P0 | done (local RC) |
| 0152 | Next-action and approval-provenance integrity | v0.4.3 Evidence Completeness | P0 | done (local RC) |
| 0153 | Cross-skill integrity dogfood and release gate | v0.4.3 Evidence Completeness | P0 | done (human-approved local RC) |
| 0153b | v0.4.3 local release preparation | v0.4.3 Evidence Completeness | P0 | done (local RC; not published) |
| 0154 | Profile boundary ADR and proposal contract freeze | v0.5.0 Council Profile | P0 | done (human accepted) |
| 0155 | Profile contract runtime and built-in registry | v0.5.0 Council Profile | P0 | done |
| 0156 | Deterministic read-only Profile request preparation | v0.5.0 Council Profile | P0 | done |
| 0157 | Profile bundle validation and dry-run planner | v0.5.0 Council Profile | P0 | done |
| 0158 | Atomic Profile bundle Evidence ingest | v0.5.0 Council Profile | P0 | done |
| 0159 | Decision proposal selection and paid/network authorization | v0.5.0 Council Profile | P0 | planned |
| 0160 | Council Discovery offline fixture E2E | v0.5.0 Council Profile | P1 | planned |
| 0161 | Council dogfood, Skill parity, and operator docs | v0.5.0 Council Profile | P1 | planned |
| 0162 | Council evaluation baseline and adoption gate | v0.5.0 Council Profile | P1 | planned |

v0.3.0 dispatch order: **0113 + 0114 in parallel** (independent; different
`evidence.py` surfaces) → **0108** (needs 0113 merged) → **0115** (freezes the
0108 contract). Shipped in v0.3.0.

v0.3.1 dispatch order: **0116 + 0117 = the integrity pair, dispatched first**
(both in `context.py`; one worker, no cross-worker merge) → 0118 canonical
target-bound docs → 0119 `pcl context check` (imports the 0116 agreement
predicate) → 0120 `pcl finish` → 0121 human-gate ja → 0122 feature_coverage
no-op.

v0.3.2 + v0.3.3 dispatch order: **0123 + 0124 in parallel** (docs-only contract
vs fixtures/tests; independent surfaces) → **0125** MCP framing (needs 0124
baseline) → 0126 conformance → **0127** outbox ADR (human gate: ADR-002
acceptance) → 0128 outbox implementation → 0129 audit commands → 0130
crash/concurrency suite. 0131 executor hardening is parallel-safe after 0124.
Wave A specs originate from `docs/roadmap/integrated/` (adopted 2026-07-10,
Accept with modifications — see `docs/roadmap/integrated/ADOPTION.md` for the
renumbering map and D-08).

v0.4.1 dispatch order: **0141** neutral idle routing → **0142** completely
plan-only repair action model → **0143** one-way consumer adding the internal
link mutation service, dedicated link commands, and explicit structural apply
→ **0144** schema-8 canonical artifact + event-hash Skill provenance → **0145**
structured findings integrating the concrete repair route → enforced-policy
dogfood. 0142 never imports or depends back on 0143 mutation code. Do not run
0142–0145 as parallel workers: adjacent slices intentionally overlap `cli.py`,
validators, Evidence services, reports, and their fixtures.

v0.4.2 dispatch order: canonical-state baseline and plan activation → **0146**
immutable Work Brief Evidence → **0147** read-only deterministic route →
**0148** JSON policy resolve/explain → **0149** explicit audited override and
optional packet refs → **0149a** two-repository dogfood/human review → **0149b**
release preparation. The proposal's embedded brief route and mutable approval
status are not adopted; see `docs/plan-v0.4.2.md`.

v0.4.3 dispatch order: **0150** target-bound evidence-set completeness →
**0151** domain-neutral completion-policy adapter and Story-linked terminal
preflight → **0152** non-idle unfinished-work routing and factual approval
provenance → **0153** incomplete/complete cross-skill dogfood, bundled Skill
parity, and human review → **0153b** local release preparation. The slices are serialized because they overlap
terminal guards, validators, routing, Evidence contracts, and fixtures. See
`docs/plan-v0.4.3.md`.

v0.5.0 Council Profile dispatch order: **0154** ADR/proposal contract freeze →
**0155** packaged validators and built-in data-only registry → **0156**
read-only request preparation → **0157** fail-closed dry-run validation →
**0158** atomic Evidence ingest/idempotency + audit orphan detection → **0159**
existing Decision + human provenance/run-authorization binding + legacy bypass
guard → **0160** offline
source/wheel/sdist E2E → **0161**
two-repository dogfood/Skill parity → **0162** frozen evaluation and human
adoption gate. See `docs/plan-v0.5.0-council-profile.md`.

## Planned next (see growth plan for scope)

| Milestone | Theme |
|---|---|
| v0.3.2 | 0123 contract docs first; optional `master_trace_context` section only after contract acceptance |
| v0.3.3 | Trust Foundation (integrated roadmap Wave A): MCP conformance + transactional outbox + recovery |
| v0.4.0 | Dogfood operations + Three-command Wedge + RC2 lifecycle Integrity Gate |
| v0.4.1 | Integrity migration: idle routing, lifecycle repair/link commands, diagnostics, Skill provenance |
| v0.4.2 | Adaptive Entry: local RC prepared; immutable brief, deterministic route, multi-axis explain/override |
| v0.4.3 | Evidence Completeness: local RC prepared; complete evidence sets, external verdict policy, approval provenance, cross-skill dogfood |
| v0.5.0 | Two tracks: Council Profile 0154–0162; separately numbered Adoption/Distribution release readiness before publication |

Everything with an ID below 0102 is completed design history; see `TASKS.md`
for the one-line summary of each.
