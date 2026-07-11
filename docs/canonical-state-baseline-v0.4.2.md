# Canonical State Baseline for v0.4.2

- **Captured:** 2026-07-11
- **Source revision:** `22997389f3edfe2c36ff18d5c76fba5e7688ff15`
- **Purpose:** Freeze the known pre-v0.4.2 Project Loop findings without
  reinterpreting historical Evidence or manufacturing human approvals.

## Authoritative audit state

After `pcl start` created `G-0018` / `T-0035`, `pcl audit check --json`
reported:

- 412 SQLite events;
- 412 JSONL events / lines;
- 412 outbox records, all delivered;
- no pending, retrying, or failed outbox records;
- no orphan completion packets, Evidence manifests, or temporary Evidence;
- 14 Evidence metadata/file mismatches, all classified `human_review`;
- no repairable or unsupported audit anomaly.

The 14 anomalies are the accepted historical baseline for comparison during
v0.4.2 development. They are not accepted as healthy Evidence. A release
candidate must introduce **zero new anomalies** relative to this list.

| Evidence | Known condition |
|---|---|
| E-0018 | one outside-root member that is now missing |
| E-0025, E-0031 | `docs/master-trace-handoff.md` changed after capture |
| E-0049 | `docs/dogfood-report-v0.4.md` changed after capture |
| E-0050, E-0052 | generated report sources changed after capture |
| E-0060 | `docs/plan-v0.4.0.md` changed after capture |
| E-0064 | `docs/release-notes/v0.4.0.md` changed after capture |
| E-0115 | v0.4.1 release note drift plus three outside-root release artifacts |
| E-0116 | `docs/release-notes/v0.4.1.md` changed after capture |

Historical records remain immutable. If current proof is needed, add a new
project-local copied Evidence record; do not rewrite these manifests.

## Lifecycle repair baseline

`pcl repair lifecycle --dry-run --json` produced 38 actions:

- structural: 0;
- semantic: 17;
- human review: 10;
- unsupported: 11.

The semantic set covers missing Feature Evidence/review state and explicit
Story choices for `TC-0002` through `TC-0006`. Human review covers Goal proof
for `G-0001` through `G-0008` and Story decisions for `TC-0001` / `TC-0007`.
Unsupported actions cover invalid or conflicting Test Evidence for `TC-0001`
through `TC-0007` and `TC-0029` through `TC-0032`.

No action is safe to auto-apply. Enabling
`validation.lifecycle_integrity: enforced` in this canonical repository is a
human gate until these meanings are reviewed or an explicit historical-policy
decision is recorded. v0.4.2 implementation must not silently satisfy that
gate.

## Configuration baseline

The canonical `pcl.yaml` previously defined empty `build`, `e2e`, and
`typecheck` commands. They were removed because this repository has no such
configured commands. `pcl doctor --strict --json` now succeeds while retaining
the 52 advisory lifecycle/Evidence findings described above.

## Reproducible checks

```bash
PYTHONPATH=src python -m pcl doctor --root . --strict --json
PYTHONPATH=src python -m pcl validate --root . --strict --json
PYTHONPATH=src python -m pcl repair lifecycle --root . --dry-run --json
PYTHONPATH=src python -m pcl audit check --root . --json
PYTHONPATH=src python -m pcl migrate status --root . --json
```
