# P0-A mutation-tail/v1 validation

- Date: 2026-07-30
- Worktree:
  `/Users/mocchalera/.agi-tools/worktrees/project-loop-harness-codex-plh-mutation-tail-p0a-20260730`
- Base HEAD: `e9bb6a08ca68428fa5f5b73f38d82816186de0e6`
- Schema migration: none
- Dependency addition: none

## Scope

Implemented:

- full-project `pcl validate` projection through additive `--target`,
  `--active-only`, and `--summary`;
- shared `mutation-tail/v1` for `feature add --task` and `task status`;
- exact-target `next_action`;
- `dashboard.auto_render` post-commit handling and `render-receipt/v1`;
- no-change suppression and committed-state recovery.

Not implemented:

- unrelated mutation handlers;
- P0-B Task terminal guard;
- `start --direct-spec`;
- `task accept`;
- Skill routing or ablation execution.

## Fail-first

Command:

```text
PYTHONPATH=src pytest -q tests/test_validation_projection.py tests/test_mutation_tail.py
```

Before runtime changes: `8 failed, 1 passed`.

The failures were the missing validate flags, missing mutation tail fields, and
missing render-failure service. The passing test froze the default/no-flag
validation contract.

## Verification

```text
PYTHONPATH=src pytest -q tests/test_validation_projection.py tests/test_mutation_tail.py tests/test_validation.py tests/test_validation_proof_scope.py tests/test_validation_finding_sources.py tests/test_tasks.py tests/test_field_feedback_0165.py tests/test_features.py tests/test_parser_builders.py tests/test_control_handlers.py tests/test_entity_handlers.py tests/test_dashboard.py
95 passed in 12.21s

ruff check .
All checks passed!

git diff --check
exit 0

PYTHONPATH=src pytest
1280 passed, 1 skipped in 294.12s
```

The full suite initially exposed only the intentional `validate --help`
baseline delta. After regenerating that single snapshot and recording the
intended additive change, the final full suite passed.

## Fresh-project smoke

Primary project:
`/tmp/pcl-p0a-smoke-20260730.KOw2Rx`

- init succeeded;
- the generic init template initially failed `doctor --strict` on its expected
  `CHANGE_ME`, empty-command, and missing-finish-check advisories;
- after setting a synthetic project name and one `true` test command,
  `doctor --strict` passed;
- validate default, target, active-only, and summary all passed;
- `feature add --task T-0001` returned exact-target next action, event
  high-watermark 14, and HTML/data artifact hashes;
- an idempotent Task status retry kept DB/JSONL events at 14 and preserved both
  dashboard hashes.

Auto-render false project:
`/tmp/pcl-p0a-smoke-false-20260730.R9W1Qx`

- response render status was `disabled`;
- HTML SHA-256 remained
  `8f35a09f1b53eb758d9abeb43de922ba3a4104f43a701cb2d51546a262c8e19a`;
- data SHA-256 remained
  `2ee1ab6f1608313ba37b319ad2bd56846da3ed74a326a961ba12290a5bcf90f2`.

Injected render-failure project:
`/tmp/pcl-p0a-smoke-failure-20260730.lJI88H`

- mutation response exited 0 with `mutation_committed=true`;
- `safe_to_retry_original=false`;
- recovery was
  `pcl validate --target T-0001 --summary --json` with `read_only` authority;
- Feature `F-0001` remained readable after the injected failure;
- recovery validation passed;
- audit was clean with 14 DB events, 14 JSONL events, and zero pending outbox
  records.
