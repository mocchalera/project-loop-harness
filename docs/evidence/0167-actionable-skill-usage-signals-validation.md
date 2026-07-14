# 0167 actionable Skill usage signals validation

Date: 2026-07-14

## Result

The first data-driven improvement cycle is complete. The original report
treated every later use of a command in a session as retry friction. It now
counts only a matching next PCL call after a classified command error, timeout,
or guarded-execution block.

Friction rows also expose deterministic command breakdowns made only from the
existing normalized allowlist. Raw commands, arguments, output, paths, and IDs
remain absent.

## Red-green evidence

Before implementation, the new acceptance fixtures reproduced the gap:

```text
PYTHONPATH=src pytest -q tests/test_skill_usage_report.py
3 failed, 7 passed in 0.55s

Failures:
- routine duplicate commands were incorrectly reported as retries;
- failure-driven matching retries could not be distinguished;
- friction rows had no normalized command breakdown.
```

After implementation:

```text
ruff check .
All checks passed!

PYTHONPATH=src pytest -q tests/test_skill_usage_report.py
10 passed in 0.46s

PYTHONPATH=src pytest -q
984 passed, 1 skipped in 195.12s

git diff --check
passed

PYTHONPATH=src python -m pcl validate --strict --json
ok: true; errors: 0; historical warnings: 37

PYTHONPATH=src python -m pcl render --json
ok: true
```

## Frozen-window comparison

Window: 2026-06-14 through 2026-07-14.

| Metric | 0166 baseline | Corrected | Change |
|---|---:|---:|---:|
| Repeated-command occurrences | 4,339 | 63 | -98.5% |
| Sessions with repeated commands | 95 | 27 | -71.6% |
| Agent Skill sessions | 176 | 176 | unchanged |
| PCL commands detected | 5,666 | 5,666 | unchanged |
| Parse errors | 0 | 0 | unchanged |

The deterministic rerun completed in 6.40 seconds and was byte-identical to the
first corrected report. Its SHA-256 was
`dc003b558bd1a1067c9ffe7a11185d02916a1bc2b486c4244658a418a8db0d52`.

A direct report scan for the local home path, user name, token-shaped values,
session/task identifier keys, and raw command/cwd keys returned
`privacy_matches=0`.

## Newly actionable signals

The corrected aggregate now identifies normalized command families without
returning to raw transcript output:

| Signal | Leading command | Occurrences | Sessions |
|---|---|---:|---:|
| Failure-driven retry | `test plan` | 9 | 5 |
| Command error | `validate` | 34 | 30 |
| Help probe | `help` | 117 | 60 |
| Timeout | `finish` | 5 | 5 |

These remain observed associations, not proven defects. The next product change
must reproduce one cluster with a sanitized fixture before implementation.

## Boundary

- No dependency, database migration, network request, external transmission,
  daemon, watcher, automatic Issue, automatic state change, or Skill rewrite.
- Multi-command tool calls associate a signal with each normalized command in
  the call. The breakdown is attribution and does not partition the signal
  total.
- Retries split across separate log shards may be undercounted.
