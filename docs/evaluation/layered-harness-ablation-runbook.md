# Layered harness minimization ablation runbook

Status: prepared; independent arm execution is not yet authorized.

This runbook freezes Task 0197 Phase 4 evaluation inputs. Preparation is
local-only. It does not count as an ablation result, does not establish model
quality, and does not authorize Phase 5 (`0198`) workflow reduction.

## Frozen inputs

- Cohort: `docs/evaluation/layered-harness-ablation-cohort.json`
- Fixture: `tests/fixtures/layered_harness_ablation_v0/layered-harness-ablation-fixture.json`
- Baseline commit: `7fa22b2` (`7fa22b23917a7847dee56d574d16a14d9649e086`)
- Treatment commit: `5ce17ec` (`5ce17ec202ad16fb67d2514fcd95e508ec489ca1`)
- Cases: exactly 8, split 3 single-session / 3 resume-handoff / 2 human-gate
- Arms: exactly 16 independent sessions (one baseline and one treatment per case)

The cohort and fixture are SHA-256-bound before the first independent arm.
Changing a case ID, prompt, oracle, metric definition, threshold, tolerance,
arm commit, or layer assignment invalidates the run and requires a new cohort
ID plus a full 16-arm rerun.

## Authorization boundary

Independent Cockpit or model-backed arms must not start until a human records:

1. session/runtime scope and the 16 arm IDs in scope;
2. data class allowed to reach any model provider;
3. run budget and expiry;
4. explicit permission to execute arms (separate from this freeze).

The prepared cohort currently records:

- `independent_agent_sessions: false`
- `network_model_provider_runs: false`
- `paid_runs: false`
- `result_fabrication: false`

Local fixture validation and focused tests do not override those flags.

## Pairing rules

Each case freezes one literal objective, prompt, fixture state kind, acceptance
oracle, allowed context, and agent runtime/model policy for both arms.

| Case | Layer | Focus |
| --- | --- | --- |
| LHA-001 | single_session | Explicit Task-bound routing in a multi-goal project |
| LHA-002 | single_session | Unbound multi-goal ambiguity safe stop |
| LHA-003 | single_session | Active vs historical validation findings |
| LHA-004 | resume_handoff | Resume from frozen handoff packet with Task target |
| LHA-005 | resume_handoff | Goal-target continuity after handoff |
| LHA-006 | resume_handoff | Shared next/resume malformed-target fail-closed behavior |
| LHA-007 | human_gate | Open decision remains visible under target binding |
| LHA-008 | human_gate | Story approval stays a human semantic gate |

Arm IDs:

- baseline: `LHA-00N-baseline` at commit `7fa22b2`
- treatment: `LHA-00N-treatment` at commit `5ce17ec`

Arms are independent sessions. Do not share memory, tool state, or notes across
arms. Do not let a treatment arm observe baseline outcomes, or the reverse.

## Consumer isolation

Each arm receives only:

- its frozen case prompt and oracle;
- the worktree checked out at its arm commit;
- the seeded fixture state for that case;
- the `project-control-loop` Skill and `pcl` CLI at that commit;
- for resume layers, the frozen handoff packet named by the case.

Do not provide:

- this freeze transcript or any other arm's transcript;
- unrecorded operator coaching;
- fabricated metrics;
- estimated provider tokens.

Result files are the only permitted write surface for evaluation output.

## Deterministic cost context

Loaded Skill bytes are a deterministic context-size measure, not a quality
claim:

| Condition | Path | Bytes | SHA-256 |
| --- | --- | --- | --- |
| baseline | `.agents/skills/project-control-loop/SKILL.md` | 17603 | `15bcd38964fa928060fe5d5567252a17337bd370dab78f4b1f9b4b64e418c2c9` |
| treatment | `.agents/skills/project-control-loop/SKILL.md` | 17433 | `630a9f94c28acee3d6a59b3fda906a7a3786fb5beab89a67ee5667cc84b6377e` |

Record the frozen byte length on every arm result. Do not re-estimate it from
memory.

## Per-arm procedure

1. Confirm authorization flags allow independent execution.
2. Verify fixture and cohort SHA-256 values still match the freeze.
3. Check out the arm commit in an isolated worktree or clean session.
4. Seed only that case's fixture state.
5. Give the agent only the allowed context for the case.
6. Run the frozen prompt to completion, safe stop, or hard stop.
7. Stop immediately on forbidden context, fixture drift, destructive action, or
   an unrecordable human-gate bypass.
8. Write one result JSON object containing every
   `required_result_fields` entry from the fixture.
9. Preserve the raw Cockpit/session ID in `session_ref`.
10. Leave failed, contaminated, missing, and safe-stopped arms visible. Never
    drop them from the denominator.

## Result capture contract

Required result fields are frozen in the fixture. Notable rules:

- `input_tokens` / `output_tokens` are `null` when the runtime does not expose
  trustworthy usage. Never invent or backfill estimates.
- `loaded_skill_bytes` must match the frozen condition value above.
- `critical_gate_violation` is boolean and remains in the denominator when true.
- `contaminated` is true if forbidden context or fixture drift occurred.
- Notes are context only; they do not replace structured fields.
- The fixture `result_example` is not a dogfood result.

## Metrics

Quality (paired booleans or counts):

- acceptance success
- target/route accuracy
- resume/handoff accuracy
- current-proof classification accuracy
- human-gate integrity
- unintended mutation count
- human intervention count

Cost (per arm):

- tool/command calls
- wall-clock seconds
- input and output tokens when trustworthy
- loaded Skill bytes

## Aggregate recommendation (Pareto)

After all 16 arms have reviewer-checkable records, aggregate with the frozen
`pareto_proceed_v0` rule:

Return `proceed` only when all of the following hold:

1. no paired quality regression;
2. no paired safety regression;
3. zero critical gate violations;
4. at least one fully observed paired cost metric strictly improves;
5. no fully observed paired cost metric worsens beyond the frozen tolerance.

Otherwise return `modify` or `stop`.

Token conclusions require complete paired non-null coverage. Other metrics
remain reportable when tokens are unavailable.

Thresholds and tolerances must not change after results are observed without a
new cohort ID and full rerun. Do not implement Phase 5 when the aggregate is
`modify` or `stop`.

## Out of scope for this freeze

- offline evaluator implementation beyond the frozen contract fields
- executing the 16 arms
- fabricating results
- runtime/code changes to `pcl`
- telemetry, paid services, or a new harness mode
