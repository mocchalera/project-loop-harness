# Finish input manifest C0 validation

- Date: 2026-07-27
- Plan: `docs/plan-pcl-real-use-friction-remediation.md`
- PCL target: `G-0067` / `T-0141` / `F-0070`
- Story / tests: `US-0068` (draft), `TC-0141`, `TC-0142`
- Scope: P0-1 Slice C0 only

## Implemented

- Added the dependency-free `verification-input-manifest/v1` collector.
- Added a content digest that excludes collection time and is stable for the same root and inputs.
- Captured tracked, untracked, policy-matched ignored output, regular file, symlink, mode, size, SHA-256, and missing tracked-file state.
- Excluded `.project-loop/**` from the verification input claim.
- Added fail-closed findings for unreadable, changing, and unsupported inputs.
- Added the four effect classifications: `read_only`, `declared_outputs`, `mutates_inputs`, and `unknown`.
- Compared the path identity before open, on the opened descriptor, after reading, and after returning to the path to detect replacement races.

## Verification

```text
PYTHONPATH=src pytest -q tests/test_verification_manifest.py
6 passed in 3.85s

PYTHONPATH=src pytest -q tests/test_finish.py tests/test_verification_manifest.py
25 passed in 19.10s

ruff check .
All checks passed!

PYTHONPATH=src pytest -q
1184 passed, 1 skipped in 599.44s (0:09:59)
```

The tests cover:

- deterministic digest and unchanged comparison;
- tracked content and executable-mode changes;
- symlink target changes;
- untracked additions;
- policy-matched ignored cache output;
- `.project-loop/**` exclusion;
- unreadable input;
- replacement after file read;
- unsupported filesystem input.

## Preserved boundaries

- No DB migration.
- No new dependency.
- No external write.
- No completion packet or terminal state change.
- Existing `pcl finish` planner and packet contracts remain unchanged.

## Residual risk / next slice

C0 is not wired into `pcl finish --emit-packet`. Finish checks still execute in the canonical project root until Slice C1 adds an isolated execution workspace and records pre/post manifests in attempt Evidence. C0 must not be presented as completion of the finish safety substrate.
