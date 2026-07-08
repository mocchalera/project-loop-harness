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
| 0102 | Source drift health warning | v0.2.4 Trust Patch | P1 | in progress |
| 0103 | SECURITY.md v0.2.x + copied-evidence policy | v0.2.4 Trust Patch | P1 | in progress |
| 0104 | Python 3.10–3.13 CI matrix | v0.2.4 Trust Patch | P2 | in progress |
| 0105 | Evidence copy observability | v0.2.4 Trust Patch | P2 | proposed (after 0102) |
| 0106 | Release checklist contract | v0.2.4 Trust Patch | P2 | done (`docs/release-checklist.md`) |
| 0107 | agent-tasks backlog index | v0.2.4 Trust Patch | P3 | done (this file) |

## Planned next (see growth plan for scope)

| Milestone | Theme |
|---|---|
| v0.3.0 | Target-bound code context receipts (`impact --for-task/--for-job`, `--require-bound-receipt`) |
| v0.3.1 | Operator experience: `pcl finish` (F7), human-gate ja copy (F5), feature_coverage no-op (F4) |
| v0.3.2 | Master trace / intent-index v0 contract formalization |
| v0.4.0 | Dogfood operations + cost KPI measurement |
| v0.5.0 | Adoption: README split, contract stability policy |

Everything with an ID below 0102 is completed design history; see `TASKS.md`
for the one-line summary of each.
