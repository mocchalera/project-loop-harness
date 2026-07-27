# P0-2 finish result / stability contract validation

- Date: 2026-07-28
- Commit: `92346bb500243022dc9106d2e268f0f7747962ae`
- Goal: `G-0067`
- Task: `T-0142`
- Feature: `F-0071`
- Story: `US-0069` (`draft`; human semantic approval was not inferred)
- Tests: `TC-0144`, `TC-0145`, `TC-0146`

## Implemented contracts

- `finish-check-result/v2` keeps legacy completion-check fields and adds:
  - `runner-result/v1`
  - `assertion-result/v1`
  - bounded `failure_phase` and `failure_kind`
  - `verification-attempt-identity/v1`
  - `stability-evaluation/v1`
- Guarded execution now records typed spawn errors, duration, artifact collection state,
  a value-free environment digest, and worker / shard / seed context digests.
- A single cold passing attempt is recorded as `stability_required` and
  `reproducible: false`.
- `completion-packet/v1` remains valid and unchanged in shape.
- `resume` retains a PCL-produced non-reproducible check as a replay command for
  gathering new stability Evidence without claiming it is already reproducible.

## Verification

### Contract and finish integration

Command:

```text
PYTHONPATH=src pytest -q tests/test_resume.py tests/test_finish.py tests/test_verification_results.py tests/test_guarded_process.py
```

Result:

```text
54 passed in 57.84s
```

The assertions cover success, non-zero exit, timeout, spawn failure, signal
termination, collection failure, deterministic attempt identity, cold / warm
policy satisfaction, exhausted mixed outcomes, incompatible identities,
completion-packet/v1 validation, and replayable non-reproducible checks.

### Full suite

Command:

```text
PYTHONPATH=src pytest
```

Result:

```text
1200 passed, 1 skipped in 551.22s (0:09:11)
```

### Lint and CLI smoke

Commands:

```text
PYTHONPATH=src python -m ruff check .
PYTHONPATH=src python -m pcl --help
```

Results:

```text
All checks passed!
pcl help rendered successfully
```

## Dogfood findings

1. `pcl next --target T-0141 --json` still selected unrelated project-level
   `DEC-0014`; no Decision state was changed. This remains assigned to P0-4.
2. Moving a Feature to `specified` requires reviewer-checkable Evidence even when
   its Story draft is already stored. The Feature was not advanced without that
   Evidence.
3. Correcting a single pass to `reproducible: false` initially removed its restart
   command from `resume`. The implementation now separates authoritative proof
   from a safe command that can gather the next stability attempt.

## Residual boundaries

- P0-2 records stability but does not change terminal outcomes. Shared terminal
  enforcement remains P0-3 work.
- Cross-attempt lookup and immutable result reuse remain P0-5 work.
- External tools without a Python distribution version use executable path / stat
  identity and an explicit null version; no unguarded version probe was added.
- No database migration, dependency addition, external write, or Story approval was
  performed.
