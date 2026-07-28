# Structured command guide

`pcl guide` is a local, read-only orientation surface for agents and operators
who know their purpose but do not yet know the full PCL command route.

```bash
pcl guide
pcl guide --json
pcl guide direct --json
pcl guide finish
```

The supported topics are:

- `start`: inspect adoption and register one literal intent;
- `direct`: deliver one Feature through Story, Test, Evidence, and Goal close;
- `finish`: preview and perform evidence-backed terminal closure;
- `dashboard`: validate, render, and prepare human review orientation;
- `recover`: diagnose a stopped or resumed loop with read-only context.

The `command-guide/v1` JSON contract returns ordered command templates. Existing
keys and command templates remain stable. Additive operator-contract fields
make the authority boundary explicit:

- `authority_class` separates `read_only`, `pcl_local_state`,
  `repository_write`, `external_write`, and `terminal_transition`;
- `human_decision_required` and `human_decision_basis` distinguish a semantic
  approval receipt from ordinary execution authority;
- `evidence_requirement` states when healthy Evidence is a terminal
  prerequisite;
- `failure_recovery` supplies an exact read-only command instead of repeating a
  failed terminal mutation.

`human_required` and `human_decision_required` do not authorize an agent to
approve on a human's behalf. Healthy Evidence also does not manufacture a
semantic decision. The local guide contains no external or production write
command, and its classification is orientation rather than an OS sandbox or
runtime permission grant.

The guide is available before `pcl init` and does not create `.project-loop`.
It complements `pcl next --json`: use `guide` to learn a purpose-oriented route
and `next` to read the authoritative recommendation for the current project
state.

## Record a repeated harness failure

When a bounded trajectory exposes an environment problem rather than only a
product defect, validate and record a `gap-report/v1`:

```bash
pcl contract validate --type gap-report/v1 gap-report.json --json
pcl gap add gap-report.json --summary "Earliest failed handoff" --dry-run --json
pcl gap add gap-report.json --summary "Earliest failed handoff" --json
pcl gap list --target task:T-0001 --gap-class context --json
```

Candidate lessons remain claims. `pcl gap promote` requires hash-bound human
provenance and records approval with durable-owner application still pending.
See [Gap Report v1](gap-report-v1.md).
