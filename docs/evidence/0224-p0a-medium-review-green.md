# P0-A Medium review follow-up validation

Date: 2026-07-30

Base commit:
`91904f3718f2a45b14e0be2d04caa6024cd5700b`

## Fail-first

Evidence `E-0003` pins the focused RED result:

```text
4 failed in 0.67s
```

The failures covered missing-database target resolution, active agent safety
projection, concurrent render provenance, and persistent invalid auto-render
configuration.

## Implementation result

1. Target resolution uses a query-only SQLite URI and returns typed
   `validation_target_resolution_unavailable` projection metadata when the
   database or required routing tables are unavailable. Missing-database and
   missing-table tests assert filesystem hashes and path sets are unchanged.
2. `agent_concurrency_exceeded`, `agent_lease_expired`, and
   `agent_retired_active_lease` are an explicit global operational-safety
   family. Projection retains the complete finding object.
3. Auto-render brackets dashboard generation with read-only event
   high-watermarks. One changed window rerenders; a second changed window
   fails closed after exactly two attempts and returns no artifact hashes.
4. Invalid `dashboard.auto_render` is a full-validation global configuration
   error. Selected connected mutations allow that non-authoritative
   post-commit error through their initialization guard, keep the committed
   mutation at exit zero, and add top-level partial diagnostics and read-only
   recovery.

## Verification

Focused Medium regressions:

```text
4 passed in 0.65s
```

Targeted validation, mutation, Task, and Feature suites:

```text
64 passed in 8.36s
```

Full suite:

```text
1286 passed, 1 skipped in 313.94s (0:05:13)
```

Static checks:

```text
ruff check .: passed
git diff --check: passed
```

Fresh isolated smoke roots:

```text
missing database:
  /tmp/pcl-p0a-medium-missing-20260730.dnsQ1n
auto-render true and invalid-config recovery:
  /tmp/pcl-p0a-medium-true-20260730.2bHndG
auto-render false:
  /tmp/pcl-p0a-medium-false-20260730.n7Tga5
```

Smoke assertions:

- missing database: exit 1, typed unavailable resolution, no `project.db`
  creation;
- doctor strict and validate strict: passed on the initialized project;
- target/active-only/summary validation: passed;
- auto-render true: stable receipt sequence 14 with equal before/after
  watermark;
- auto-render false: HTML and data SHA-256 values unchanged;
- invalid config mutation: exit 0, `mutation_committed=true`,
  `post_commit_status=partial`, retry prohibited;
- recovery validation: exit 1 with
  `config_dashboard_auto_render_invalid`.

## Residual boundary

No schema migration, dependency, telemetry, P0-B behavior, external write, or
push was introduced.

The review Low remains unresolved: real disk-full/EACCES and a failure between
the renderer's two artifact writes are covered only by injected `OSError`, not
an operating-system fault environment.

The task-local Story remains draft because the current approval CLI cannot
record the required human approver, recorder, source kind, and source reference
provenance. The four PCL Tests therefore retain their fail-first states; this
artifact records the current GREEN implementation evidence without fabricating
semantic approval.
