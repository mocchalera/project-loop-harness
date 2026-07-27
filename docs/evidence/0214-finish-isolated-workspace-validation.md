# Finish isolated workspace C1 validation

- Date: 2026-07-27
- Plan: `docs/plan-pcl-real-use-friction-remediation.md`
- PCL target: `G-0067` / `T-0141` / `F-0070`
- Story / test: `US-0068` (draft), `TC-0143`
- Scope: P0-1 Slice C1

## Implemented

- `pcl finish --emit-packet` records a canonical `verification-input-manifest/v1` before execution.
- Finish creates a temporary `git clone --no-local` workspace, verifies that its Git common directory differs from the canonical checkout, removes `origin`, and materializes dirty tracked and untracked inputs.
- Root `node_modules` is copied only when a Node/package-manager check needs it; the copy is not a symlink or hardlink to canonical files.
- The guarded executor accepts an explicit execution root while retaining canonical Evidence staging.
- Pre/post workspace manifests classify check effects as `read_only`, `declared_outputs`, `mutates_inputs`, or `unknown`.
- `read_only` and declared ignored outputs retain completion-packet/v1 behavior.
- `mutates_inputs` and `unknown` create content-addressed `finish-attempt/v1` Evidence plus check Evidence and `finish_attempt_recorded`; they create no completion packet and do not transition the target.
- The canonical repository snapshot race guard remains active and no automatic restoration was added.

## Verification

```text
PYTHONPATH=src pytest -q \
  tests/test_guarded_process.py \
  tests/test_workflow_sandbox.py \
  tests/test_finish.py \
  tests/test_finish_workspace.py \
  tests/test_verification_manifest.py
61 passed in 18.39s

PYTHONPATH=src pytest -q \
  tests/test_verification_manifest.py \
  tests/test_finish_workspace.py \
  tests/test_finish.py
28 passed in 16.53s

ruff check .
All checks passed!

PYTHONPATH=src pytest -q
1187 passed, 1 skipped in 526.83s (0:08:46)
```

The integration fixture runs a passing pytest check that writes a tracked file.
The check sees an isolated working copy and returns exit 0, but finish:

- leaves the canonical tracked file byte-identical;
- classifies the effect as `mutates_inputs`;
- stores one `finish_attempt` and its check Evidence;
- stores zero `completion_packet` Evidence;
- leaves the Task `in_progress`;
- passes strict validation afterward.

The workspace unit fixtures also verify dirty file content, executable mode,
symlink target, untracked file materialization, independent Git metadata,
origin removal, cleanup, and an independently copied `node_modules`.

## Preserved boundaries

- No DB migration.
- No new dependency.
- No OS or network sandbox claim.
- No external write.
- No automatic canonical checkout restore.
- Existing plan-only finish behavior and completion-packet/v1 validation remain compatible.

## Residual risk / next slice

- Absolute-path writes and writes through external environments remain outside the repository-copy guarantee.
- Only a root `node_modules` dependency tree is copied automatically; workspace-specific package layouts need later typed configuration or a stronger backend.
- A single exit 0 is still represented by the existing check result fields. Runner/assertion separation and stability evaluation belong to P0-2.
- `resume` and `next` do not yet consume `finish-attempt/v1`; attempt-aware routing belongs to the result/readiness slices.
