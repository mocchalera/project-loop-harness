# 0160 Council Discovery offline E2E validation

**Date:** 2026-07-12

**Provider/network/paid service/API key:** none

**SQLite schema:** 8, unchanged

## Boundary proof

`pcl profile fixture-run` consumes a valid offline request and an explicit
scenario name. It writes only the named output directory and reports
`provider_code_present: false`, `network_used: false`,
`paid_service_used: false`, and `plh_state_mutated: false`.

The runner emits the same bytes for the same request/status. Its verification
commands remain inert strings. It produces all six valid statuses plus one
malformed hash scenario that the normal ingest validator rejects.

## Complete flow

The reusable E2E script exercises:

```text
init → start → Brief add → route record → Profile prepare
→ fixture-run twice → byte equality → ingest dry-run → ingest
→ next → proposal show → human select
→ separate revised Brief add → human review → human approval
```

Before selection, both plain `decision resolve` and `decision waive` are
rejected with `decision_proposal_command_required` and zero mutation. Selection
does not approve either the original or revised Brief.

For `partial`, `budget_exhausted`, and `failed`, the bundle next action remains
`safe_to_run: false`. Failed ingest still requires explicit acceptance.

## Package environments

- Source: all seven scenarios run through the reusable E2E.
- Installed wheel: needs-human E2E including Decision and separate Brief gate.
- Extracted sdist: completed E2E from the archive source and archived test
  fixture.

The wheel and sdist include the scenario descriptor, validators, manifest,
fixture runner, and E2E fixture files.

## Verification

```text
$ ruff check .
All checks passed!

$ PYTHONPATH=src pytest -q tests/test_profile_fixture_e2e.py \
    tests/test_distribution.py tests/test_profile_ingest_dry_run.py \
    tests/test_profile_prepare.py
65 passed

$ PYTHONPATH=src pytest -q
935 passed, 1 skipped
```
