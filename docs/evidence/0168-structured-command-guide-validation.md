# 0168 structured command guide validation

Date: 2026-07-14

## Result

The second data-driven improvement cycle is complete. The corrected local
Skill usage report observed 768 help probes across 93 sessions, led by 117 root
help probes in 60 sessions. PCL now provides a single purpose-oriented,
machine-readable guide instead of requiring an agent to reconstruct a route
from multiple argparse help pages.

`pcl guide --json` returns `command-guide/v1` with five ordered topics:
`start`, `direct`, `finish`, `dashboard`, and `recover`. Each step declares its
command template, state-mutation boundary, run policy, substitutions, purpose,
and expected outcome. An explicit `human_required` step preserves Story
approval as a human gate.

Implementation commits:

- `8c09c8e` — specify the structured command guide;
- `51ba5b5` — implement the CLI, contract, Skill parity, docs, tests, and
  dogfood-report recognition.

## Red-green evidence

Before implementation:

```text
PYTHONPATH=src pytest -q tests/test_command_guide.py
4 failed in 0.48s

All failures were the absent `guide` CLI surface.
```

After implementation:

```text
PYTHONPATH=src pytest -q tests/test_command_guide.py
5 passed in 0.47s

PYTHONPATH=src pytest -q \
  tests/test_command_guide.py \
  tests/test_skill_usage_report.py \
  tests/test_skill_command_examples.py \
  tests/test_baseline_fixtures.py
43 passed in 5.15s

ruff check .
All checks passed!

git diff --check
passed

PYTHONPATH=src pytest -q
990 passed, 1 skipped in 215.40s
```

## Initialization-independent smoke

A fresh empty directory was used without `pcl init`:

```text
topics: start, direct, finish, dashboard, recover
first JSON SHA-256:  92e5d24951234e2ea882d0f9bb9ca5675e9840bc57252781656044a4e202e8b5
second JSON SHA-256: 92e5d24951234e2ea882d0f9bb9ca5675e9840bc57252781656044a4e202e8b5
.project-loop created: false
unknown topic exit: 2
unknown topic code: invalid_input
```

Every documented command template was also placeholder-substituted and parsed
through the current CLI parser contract in the focused suite.

## Distribution and measurement

All four loaded and distributed Project Control Loop Skill copies are
byte-identical and tell an agent to use one structured guide lookup only when
the route or syntax is genuinely unclear.

The privacy-safe dogfood normalizer now recognizes `guide` as a command family
without retaining its topic or arguments. The first post-implementation local
smoke observed two guide calls in one session, while the report still declared:

```text
raw content retained: false
command arguments retained: false
session identifiers retained: false
workspace paths retained: false
external transmission: false
```

This proves measurement wiring, not a reduction in help probes. Effectiveness
must be evaluated on a later fixed window after agents have used the updated
Skill.

## Boundary

- No database migration, dependency, network request, telemetry, daemon,
  hosted state, automatic command execution, or external transmission.
- `pcl guide` does not inspect or mutate project state.
- Existing `pcl next --json` behavior and all existing command syntax remain
  unchanged.
