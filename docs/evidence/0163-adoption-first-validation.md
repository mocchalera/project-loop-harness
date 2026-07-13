# 0163 Adoption-first validation

- Date: 2026-07-13
- Implementation commit: `ac25288`
- Goal: `G-0024`
- Task: `T-0045`
- Source review: Cockpit task `524a3d14`
- Milestone review: Cockpit task `9638926d`

## Delivered

- Preserved the business/technical review with source provenance.
- Activated Adoption / Distribution ahead of additional Council and v0.5.1
  feature work across the canonical backlog and roadmap surfaces.
- Added a 30-second value path, five-minute setup, and agent-owned routine loop
  to README.
- Documented inspect-first coexistence and the exact `--force` boundary.
- Added the alpha stability policy for versioned JSON, typed errors, migrations,
  and explicitly internal surfaces.
- Replaced the expired fixed authorization-test timestamp with current UTC plus
  one day while preserving expired-input rejection tests.

## Verification

- `PYTHONPATH=src pytest -q tests/test_adoption_docs.py tests/test_profile_ingest_dry_run.py`
  — 52 passed after review fixes.
- `PYTHONPATH=src pytest -q` — 960 passed, 1 skipped in 243.90 seconds.
- `ruff check .` — passed.
- `git diff --check` — passed.
- Claude Fable independently ran the target tests and full suite, checked init
  coexistence against implementation, requested one README correction, and
  returned unconditional `APPROVE` after all findings were resolved.

## Boundaries retained

- No push, tag, release, external post, provider execution, paid service,
  telemetry, dependency, schema migration, default Council activation, or
  automatic GitHub write.
- Council remains opt-in; the human adoption outcome remains
  `continue experiment`.
- The visual demo and launch content remain the next P1 launch-packet work.
- The next P0 is local v0.5.0 release-candidate preparation followed by a
  separate human publication decision.
