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

## Planned next (see growth plan for scope)

| Milestone | Theme |
|---|---|
| v0.3.2 | 0123 contract docs first; optional `master_trace_context` section only after contract acceptance |
| v0.3.3 | Trust Foundation (integrated roadmap Wave A): MCP conformance + transactional outbox + recovery |
| v0.4.0 | Dogfood operations + cost KPI measurement + first-class Intent/Collection decision |
| v0.4.x | Possible `pcl intent` / `pcl collect` design if dogfood shows repeated need; integrated Wave B (3-command wedge) decision |
| v0.5.0 | Adoption: README split, contract stability policy, upstream-layer adoption decision |

Everything with an ID below 0102 is completed design history; see `TASKS.md`
for the one-line summary of each.
