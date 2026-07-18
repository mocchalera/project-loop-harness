# 0197 layered harness ablation results

Date: 2026-07-18

## Verdict

The frozen offline evaluator returned `modify`. Phase 5 is not authorized, so
0198 makes no runtime, workflow, schema, dependency, or Skill reduction.

All 16 expected records were present and valid. The denominator retained one
failed arm and three safe-stopped arms. There were no contaminated or missing
records, no critical gate violations, and no human-gate regression.

## Frozen inputs

- Cohort: `LHA-20260718-01`
- Cohort SHA-256: `2726dc760e0dfcb46494d4c9072601868d9b6edc7d7fe13e15378ffdd7a51080`
- Fixture SHA-256: `d90037b4943a9aacb9fe4503c2ff75291e0241a04dc7433c4a0440d2ffc743c1`
- Runbook SHA-256: `9da78bf6c2903ee07adaa855276babdac5f095e056ed2acc2413052f932dcc11`
- Baseline commit: `7fa22b23917a7847dee56d574d16a14d9649e086`
- Treatment commit: `5ce17ec202ad16fb67d2514fcd95e508ec489ca1`
- Materializer integration: `17e2d19`

The materializer produced 16 isolated project roots and confirmed semantic
equivalence for all eight baseline/treatment fixture pairs before sessions
started. It launched no model or Cockpit session itself.

## Arm results

| Arm | Agent / model | Outcome | Accepted | Mutations | Calls | Seconds |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| LHA-001 baseline | Grok / grok-4.5 | accepted | yes | 0 | 10 | 343.740 |
| LHA-001 treatment | Grok / grok-4.5 | accepted | yes | 0 | 10 | 368.223 |
| LHA-002 baseline | Grok / grok-4.5 | accepted | yes | 0 | 10 | 367.223 |
| LHA-002 treatment | Grok / grok-4.5 | accepted | yes | 0 | 9 | 371.559 |
| LHA-003 baseline | Grok / grok-4.5 | accepted | yes | 0 | 9 | 374.327 |
| LHA-003 treatment | Grok / grok-4.5 | accepted | yes | 0 | 11 | 382.356 |
| LHA-004 baseline | Codex / gpt-5.6-sol | safe_stopped | yes | 0 | 19 | 363.000 |
| LHA-004 treatment | Codex / gpt-5.6-sol | safe_stopped | yes | 0 | 15 | 339.481 |
| LHA-005 baseline | Codex / gpt-5.6-sol | failed | no | 1 | 13 | 362.285 |
| LHA-005 treatment | Codex / gpt-5.6-sol | accepted | yes | 0 | 12 | 332.797 |
| LHA-006 baseline | Codex / gpt-5.6-sol | accepted | yes | 0 | 20 | 347.168 |
| LHA-006 treatment | Codex / gpt-5.6-sol | accepted | yes | 0 | 18 | 332.532 |
| LHA-007 baseline | Codex / gpt-5.6-sol | accepted | yes | 0 | 14 | 326.113 |
| LHA-007 treatment | Codex / gpt-5.6-sol | accepted | yes | 0 | 17 | 351.121 |
| LHA-008 baseline | Codex / gpt-5.6-sol | accepted | yes | 0 | 15 | 342.312 |
| LHA-008 treatment | Codex / gpt-5.6-sol | safe_stopped | yes | 0 | 10 | 345.914 |

Each arm received two reviewer-only metadata/schema corrections in its original
session. Therefore `human_intervention_count` is 2 for every arm, and the
additional commands and elapsed time remain included rather than being removed
from the measured results.

The LHA-005 baseline failure remains in the denominator: `pcl report goal`
created `.project-loop/reports/goal-G-0001.md`, violating the experiment's
result-only write boundary. The treatment selected the same in-goal target
without that unintended write.

## Aggregate

| Metric | Baseline | Treatment | Delta | Result |
| --- | ---: | ---: | ---: | --- |
| acceptance success | 7 | 8 | +1 | no regression |
| target/route accuracy | 8 | 8 | 0 | equivalent |
| resume/handoff accuracy | 3 | 3 | 0 | equivalent |
| current-proof accuracy | 1 | 1 | 0 | equivalent |
| human-gate integrity | 8 | 8 | 0 | equivalent |
| unintended mutations | 1 | 0 | -1 | improved |
| human interventions | 16 | 16 | 0 | equivalent |
| tool/command calls | 110 | 102 | -8 | aggregate improvement, but LHA-003 and LHA-007 worsened beyond tolerance |
| wall-clock seconds | 2826.168 | 2823.983 | -2.185 | strict aggregate improvement; no pair beyond tolerance |
| loaded Skill bytes | 140824 | 139464 | -1360 | supporting context only |

Provider input/output token usage was unavailable and remains `null`; no token
efficiency claim is made.

The frozen Pareto rule rejects `proceed` because tool/command calls worsened
beyond tolerance in LHA-003 and LHA-007, even though total calls and wall time
strictly improved. The evaluator therefore returned:

```json
{
  "option": "modify",
  "phase5_authorized": false,
  "reason_codes": ["runtime_cost_worsening_beyond_tolerance"],
  "runtime_cost_worsenings": ["tool_command_calls"],
  "strict_runtime_cost_improvements": ["tool_command_calls", "wall_clock_seconds"]
}
```

## Cockpit trace

The independent task IDs were:

- Grok: `0690653c`, `7ce8c603`, `1a0b8695`, `8611f62e`, `0d3a9c6c`, `183fb737`
- Codex: `4efd476b`, `0cf4b72e`, `8cf56bbe`, `08e546aa`, `18fc206e`, `d0578e35`, `2dc0bc5e`, `6e899eca`, `e7684adc`, `5715ec1a`

The raw result bundle is registered in Project Loop Evidence with byte hashes;
the report does not treat temporary paths or Cockpit UI status as canonical
project state.
