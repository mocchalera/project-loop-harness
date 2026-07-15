# Evidence 0176: scale baseline and event-log policy

## Scope

Documentation and deterministic fixture only. No runtime rotation/compaction,
schema, dependency, telemetry, provider, CLI contract, or release changes.

## Reference measurement

At revision `67cb42190bcf99921b4fc7fed8a8d8ade9259ac1` on 2026-07-15:

- `.project-loop/events.jsonl`: 1,207 lines, 628,896 bytes;
- SQLite `events`: 1,207 rows, sequences 1 through 1,207;
- SQLite `outbox_records`: 1,207 rows;
- 38 Goals, 38 Features, 36 Stories, 101 Tests, 61 Tasks, 374 Evidence;
- `dashboard-data.json`: 156,713 bytes;
- dashboard HTML: 109,580 bytes;
- `.project-loop`: 15 MiB; `project.db`: 3,579,904 bytes.

The values are a dated observation, not a performance claim or SLO.

## Delivered artifacts

- `docs/scale-baseline-event-log-policy.md` — reference snapshot, advisory S0–S3 bands, benchmark contract, and future rotation/compaction invariants.
- `tests/fixtures/scale_baseline_v1/manifest.json` — deterministic synthetic workload manifest for 1k, 10k, and 100k event cases.
- `tests/fixtures/scale_baseline_v1/README.md` — fixture regeneration and non-enforcement boundary.
- `tests/test_scale_baseline_fixture.py` — contract checks for ordering, event mix, workload sizes, and disabled runtime enforcement.

## Verification

```text
PYTHONPATH=src pytest -q tests/test_scale_baseline_fixture.py
1 passed in 0.01s

ruff check tests/test_scale_baseline_fixture.py
All checks passed!

python -m json.tool tests/fixtures/scale_baseline_v1/manifest.json
success

git diff --check
success
```

## Boundary

The fixture is descriptive. Any future benchmark runner must use a temporary
project and emit separate result artifacts. Thresholds do not trigger runtime
rotation or compaction automatically; a future implementation requires an
approved task and an auditable backup/replay design.
