# 0152 Next action and approval provenance validation

**Date:** 2026-07-11
**Scope:** passing-Feature next-action routing, missing completion-receipt
diagnostics, hash-bound review/approval provenance, context/resume/dashboard
surfaces, compatibility, and package verification.

## Implemented

- Added a non-idle `review_passing_feature_completion` route before generic
  open-goal continuation. The route identifies missing Evidence Set and
  Completion Policy receipts and points to a safe read-only Evidence command.
- Added additive `approval-provenance/v1` event receipts with action,
  `actor_kind`, actor identity, source command, timestamp, target, bound
  Evidence ID/SHA-256, and reason.
- Added `pcl brief review` for human, agent, or system review without approval.
- Restricted `pcl brief approve` to human-origin provenance. Namespaced actor
  and explicit actor-kind mismatches fail before mutation.
- Surfaced approval provenance through Work Brief JSON, task context packs,
  resume handoffs, and deterministic dashboard data.
- Preserved legacy human-namespaced Work Brief approval calls while rejecting
  agent self-approval and retaining DB schema 8.

## Verification

### Focused and related regression tests

```text
PYTHONPATH=src python -m pytest -q \
  tests/test_work_briefs.py tests/test_next_actions.py \
  tests/test_dashboard.py tests/test_dashboard_data_contract.py \
  tests/test_context.py tests/test_resume.py \
  tests/test_route_recommendation.py tests/test_route_overrides.py \
  tests/test_baseline_fixtures.py
140 passed in 37.64s

PYTHONPATH=src python -m pytest -q \
  tests/test_defects.py tests/test_next_actions.py tests/test_work_briefs.py \
  tests/test_handoff_packet_contract.py
39 passed in 5.67s
```

Coverage includes passing-but-not-done routing, missing completion-policy
receipt diagnostics, agent review, zero-trace agent approval rejection,
explicit human approval, actor namespace mismatch guards, hash binding,
idempotency, context/resume provenance, dashboard ordering, and the existing
defect-to-passing lifecycle.

### Full suite and static checks

```text
PYTHONPATH=src python -m pytest -q
833 passed, 1 skipped in 178.17s

PYTHONPATH=src python -m ruff check .
All checks passed!

git diff --check
exit 0
```

The first full run exposed one old test that expected a closed defect's
`passing` Feature to route to `idle`. Its assertion was updated to the new
specified completion-review route; the final full run above is green.

### Package and clean-wheel smoke

```text
python -m build --outdir /tmp/pcl-0152-final2-dist.hsPUca
Successfully built project_loop_harness-0.4.2.tar.gz and
project_loop_harness-0.4.2-py3-none-any.whl
```

The final wheel was installed into
`/tmp/pcl-0152-final-wheel.6RGQMO`. `pcl brief --help` exposed `review`, the
installed `pcl.approval_provenance` module resolved inside the isolated
environment, and the packaged handoff schema carried the expected
`^sha256:[0-9a-f]{64}$` approval binding.

An end-to-end clean-wheel smoke at
`/tmp/pcl-0152-wheel-smoke.Y8Htgt` recorded an agent review, rejected an agent
approval with exit 1, accepted explicit human approval, rendered dashboard
data, and returned ordered human then agent provenance receipts.

## Boundary retained

These receipts record caller-supplied provenance but do not authenticate
identity; identity federation remains out of scope. PCL does not auto-complete
a passing Feature or invent readiness. DB schema remains 8 and no dependency
was added. No commit, tag, push, release, or publication was performed.
