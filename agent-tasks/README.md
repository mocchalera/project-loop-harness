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
| 0116 | Target-bound receipt / link agreement validation | v0.3.1 Handoff Integrity | P1 | merged to main (v0.3.1, unreleased) |
| 0117 | Target-specific refresh command in code-context Markdown | v0.3.1 Handoff Integrity | P1 | merged to main (v0.3.1, unreleased) |
| 0118 | Canonical target-bound handoff docs (README + adoption) | v0.3.1 Operator Experience | P1 | done (main, v0.3.1 unreleased) |
| 0119 | `pcl context check` read-only preflight | v0.3.1 Operator Experience | P1 | merged to main (v0.3.1, unreleased) |
| 0120 | `pcl finish` terminal close-out planner (F7) | v0.3.1 Operator Experience | P1 | spec ready |

v0.3.0 dispatch order: **0113 + 0114 in parallel** (independent; different
`evidence.py` surfaces) → **0108** (needs 0113 merged) → **0115** (freezes the
0108 contract). Shipped in v0.3.0.

v0.3.1 dispatch order: **0116 + 0117 = the integrity pair, dispatched first**
(both in `context.py`; one worker, no cross-worker merge) → 0118 canonical
target-bound docs → 0119 `pcl context check` (imports the 0116 agreement
predicate) → 0120 `pcl finish` → 0121 human-gate ja → 0122 feature_coverage
no-op.

## Planned next (see growth plan for scope)

| Milestone | Theme |
|---|---|
| v0.3.1 | Operator experience: `pcl finish` (F7), human-gate ja copy (F5), feature_coverage no-op (F4), `pcl context check` preflight |
| v0.3.2 | Master trace / intent-index v0 contract formalization |
| v0.4.0 | Dogfood operations + cost KPI measurement |
| v0.5.0 | Adoption: README split, contract stability policy |

Everything with an ID below 0102 is completed design history; see `TASKS.md`
for the one-line summary of each.
