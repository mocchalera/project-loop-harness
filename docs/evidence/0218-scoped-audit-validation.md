# 0218 P0-5a Scoped Audit Validation

## Scope

- Goal: `G-0068`
- Task: `T-0145`
- Feature: `F-0074`
- Story: `US-0072` (`draft`)
- Tests: `TC-0155`–`TC-0158` (`planned`)
- Implementation commit: `6794ce9`

This slice implements read-only scoped audit diagnostics. It does not approve
the Story, pass the PCL Tests, migrate the database, add dependencies, repair
audit state, or implement immutable check-result reuse.

## Contract

- `pcl audit check --target <T-XXXX|G-XXXX>` resolves the existing shared
  `routing-target/v1` scope. Missing and malformed targets fail closed.
- `--since <EV-...|ISO-8601>` uses an inclusive related-event or
  Evidence-creation provenance anchor. Unknown events, invalid timestamps, and
  timezone-free timestamps return typed exit-2 errors.
- `--summary` returns `audit-summary/v1` grouped by proof scope,
  classification, severity, failure kind, and target without full anomaly
  rows.
- `audit-scope/v1` reports scanned, matched, excluded, and unanchored anomaly
  counts plus the explicit target and normalized boundary.
- With no scoped flags, the original six-key `audit-check/v1` JSON shape and
  audit exit semantics are unchanged.
- All paths remain read-only. Tests hash SQLite and `events.jsonl` before and
  after the scoped command.

## Fail-first

```text
PYTHONPATH=src pytest -q tests/test_audit_commands.py \
  -k 'target_scope or since_event or summary_groups or clean_is_read_only'

3 failed, 1 passed, 15 deselected
```

All three new behavior paths initially failed at argument parsing because the
flags did not exist.

## Green verification

```text
PYTHONPATH=src pytest -q tests/test_audit_commands.py \
  tests/test_audit_log_integrity.py

28 passed in 3.74s
```

```text
PYTHONPATH=src pytest -q tests/test_audit_commands.py \
  tests/test_audit_log_integrity.py tests/test_skill_command_examples.py \
  tests/test_cli_init.py \
  -k 'audit or skill_command_examples or installed_skill'

59 passed, 30 deselected in 3.41s
```

```text
PYTHONPATH=src pytest -q

1222 passed, 1 skipped in 574.63s (0:09:34)
```

```text
ruff check .

All checks passed!
```

`git diff --check` passed, and all four Project Control Loop Skill copies were
byte-identical.

## Repository dogfood

Boundary: start event `EV-F70052078EA9`, sequence `2068`.

```text
PYTHONPATH=src python -m pcl audit check \
  --target T-0145 --since EV-F70052078EA9 --summary --json

exit 0
target_binding: task T-0145, source explicit
scanned_anomalies: 77
matched_anomalies: 0
excluded_anomalies: 77
summary.total: 0
```

The unfiltered command still returned exit 6 with 77 pre-existing anomalies
and exactly these top-level keys:

```text
anomalies, contract_version, counts, hashes, ok, status
```

`--target T-9999` returned exit 2 with
`error.code=audit_target_not_found`; it did not infer another target or treat
the Task ID as a project root.

## Residual boundaries

- Scoped audit still performs the full integrity scan before filtering; this
  slice reduces diagnosis/output volume, not scan cost.
- `--since` scopes by immutable PCL provenance anchors. It does not infer the
  time at which a mutable source file drifted.
- True before/after finding-set delta and compatible immutable result reuse are
  P0-5b work.
- Finish dry-run summary/pagination/machine-state exclusion and repeated
  active-Task start idempotency remain P0-5c work.
- The 77 unfiltered anomalies are pre-existing project history and were not
  repaired or hidden by this task.
- Adopter Cockpit task `81812d6f` remained completed; monitoring did not mutate
  adopter state.
