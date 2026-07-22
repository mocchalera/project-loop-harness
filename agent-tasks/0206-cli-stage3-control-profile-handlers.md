# 0206: CLI Stage 3 control and Profile handlers

- **Status:** Complete
- **Milestone:** Post-v0.5.3 maintainability
- **Priority:** P1
- **Size:** M
- **Dependency:** 0205
- **DB schema:** remains 8

## Goal

Extract Profile, contract, Evidence Set, completion, Work Brief, Gap Report,
route/policy, initialization, audit/repair, context, index/eval, export/report,
and remaining CLI orchestration from `cli.py`.

## Acceptance

1. Existing human gates, dry-run boundaries, artifacts, and update-check
   behavior remain unchanged.
2. Characterization tests pin moved JSON/text/error branches.
3. Targeted tests, Skill examples, distribution tests, Ruff, and full pytest
   pass.
