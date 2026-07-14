# 0165 v0.4.3 field-feedback validation

Date: 2026-07-14

## Result

All eight reported friction points are covered without a dependency addition or
database migration.

| Feedback | Result | Verification |
|---|---|---|
| Finish-check setup appears too late | Fixed | `start` warning, structured `doctor` finding, typed finish error |
| Safe `git diff --check` is blocked | Fixed | exact argv allowed; neighboring Git argv blocked |
| Copied outside Evidence becomes unhealthy | Fixed | canonical copy hash controls health; source churn is informational |
| `pcl next` starts redundant coverage | Fixed | terminal direct work routes to finish/check setup |
| Bad Evidence warning cannot be retired | Fixed | `evidence supersede` records an immutable link and event |
| PCL runtime files become repository risk | Fixed | `.project-loop/**` is emitted as `harness_local_state` |
| Unused commands fail strict doctor checks | Fixed | `null` and `disabled: true` are intentional disablement |
| Task and Feature remain independent | Fixed | `feature add --task` links them atomically |

## Automated verification

```text
PYTHONPATH=src pytest -q tests/test_field_feedback_0165.py \
  tests/test_finish.py tests/test_evidence_add.py \
  tests/test_workflow_sandbox.py tests/test_next_actions.py \
  tests/test_cli_init.py tests/test_evidence_show.py tests/test_tasks.py \
  tests/test_completion_packet_contract.py
155 passed in 15.49s

PYTHONPATH=src python -m ruff check .
All checks passed!

PYTHONPATH=src pytest -q
974 passed, 1 skipped in 214.53s

git diff --check -- ':!.claude' ':!pcl.yaml'
passed
```

Current Project Loop state also passed non-strict validation and rendering.
Strict validation returned `ok: true`; its warnings are pre-existing historical
lifecycle and Evidence advisories, not 0165 regressions.

## Fresh-project smoke

Smoke root: `/tmp/pcl-0165-smoke.D8wKuk`

```text
PYTHONPATH=src python -m pcl init --target <smoke-root> --json
created: true

PYTHONPATH=src python -m pcl --root <smoke-root> doctor --json
ok: true; actionable config_finish_checks_missing warning present

PYTHONPATH=src python -m pcl --root <smoke-root> validate --json
ok: true; 0 errors; 0 warnings

PYTHONPATH=src python -m pcl --root <smoke-root> render --json
ok: true
```

## Residual boundary

- Only exact `git diff --check` is newly allowed; general Git execution remains
  blocked.
- Supersession hides only the old artifact-health warning. The old Evidence,
  manifest, relationship, and event remain auditable.
- `harness_local_state` is an optional additive packet field so older packet
  readers remain compatible.
