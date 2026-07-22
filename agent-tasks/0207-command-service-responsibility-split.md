# 0207: Command service responsibility split

- **Status:** Complete
- **Milestone:** Post-v0.5.3 maintainability
- **Priority:** P1
- **Size:** M
- **Dependency:** 0206
- **DB schema:** remains 8

## Goal

Turn `pcl.commands` into a compatibility facade over responsibility-specific
domain, next-action routing, and finish-planning modules.

## Acceptance

1. Existing imports such as `pcl.commands.create_goal`, `loop_status`,
   `build_next_action`, and `to_pretty_json` remain valid.
2. Query ordering, transactions, event payloads, routing priority, and finish
   plans remain byte-for-byte compatible where serialized.
3. Direct service tests, next-action tests, Ruff, and full pytest pass.
