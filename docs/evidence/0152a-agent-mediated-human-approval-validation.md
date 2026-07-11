# 0152a Agent-mediated human approval validation

**Date:** 2026-07-11
**Scope:** conversational/Cockpit human approval recorded by an agent without
requiring routine human CLI operation.

## Implemented

- Separated the human approver (`actor_kind` / `actor`) from the PCL mutation
  recorder (`recorder_kind` / `recorder`).
- Added `source_kind` and `source_ref` to preserve the conversation, Cockpit,
  API, or direct-CLI origin of the decision.
- Required agent/system-mediated human approval to use a non-empty
  conversation or Cockpit source reference; missing provenance rejects before
  event, outbox, or approval mutation.
- Kept direct human CLI approval as a compatibility path, while documenting
  conversation-first approval as the normal agent-facing workflow.
- Surfaced the recorder and source reference through Work Brief JSON, context
  packs, resume handoffs, dashboard data, and all bundled Project Loop Skill
  copies.

## Verification

```text
PYTHONPATH=src python -m pytest -q \
  tests/test_work_briefs.py tests/test_handoff_packet_contract.py \
  tests/test_context.py tests/test_resume.py tests/test_dashboard_data_contract.py
96 passed in 16.30s

PYTHONPATH=src python -m pytest -q \
  tests/test_skill_command_examples.py tests/test_baseline_fixtures.py \
  tests/test_distribution.py tests/test_work_briefs.py \
  tests/test_route_recommendation.py tests/test_route_overrides.py
48 passed in 14.30s

PYTHONPATH=src python -m pytest -q
833 passed, 1 skipped in 135.18s

PYTHONPATH=src python -m ruff check .
All checks passed!

git diff --check
exit 0
```

The package build at `/tmp/pcl-mediated-approval-dist.K1dNjR` produced the
wheel and sdist successfully. A clean-wheel smoke at
`/tmp/pcl-mediated-approval-wheel.EtmuaS` verified that:

1. a human approver plus agent recorder without a conversational/Cockpit
   source was rejected with exit 2;
2. the same approval with
   `source_kind=conversation` and a non-empty `source_ref` succeeded;
3. `pcl brief show` returned distinct human approver and agent recorder fields
   bound to the immutable Work Brief SHA-256.

## Product boundary

The human only needs to approve, reject, hold, or request evidence in the
conversation/Cockpit UI. The agent performs the PCL mutation on a later turn.
The receipt records this delegation but does not authenticate identities or
scrape private conversation content. DB schema remains 8, no dependency was
added, and no commit, push, tag, release, or publication was performed.
