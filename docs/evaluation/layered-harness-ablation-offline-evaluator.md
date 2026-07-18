# Layered harness ablation offline evaluator

This is the local-only T-0116 preparation and evaluation surface. It does not
launch Cockpit tasks, call a model, authorize the prepared arms, mutate Project
Loop state, or authorize Phase 5.

The human authorization is a separate receipt; the frozen cohort remains
unchanged. The receipt must be an exact-schema JSON object containing:

- `contract_version`: `layered-harness-ablation-authorization/v1`
- the frozen `cohort_id` and `cohort_sha256`
- all 16 `authorized_arm_ids` exactly once
- `independent_cockpit_sessions: true` and
  `network_model_provider_runs: true`
- exactly the frozen `authorized_agent_types` (`codex`, `grok`)
- nonempty `data_class`, `cost_policy`, and `authorized_by`
- `budget` with `currency`, nonnegative `max_amount`, and boolean
  `paid_runs_allowed`
- UTC `authorized_at` and a later, unexpired UTC `expires_at`

Prepare the 16 independent-session packets in an empty directory:

```bash
python scripts/evaluate_layered_harness_ablation.py prepare \
  --output-dir /tmp/lha-arm-packets \
  --authorization /path/to/user-authorization.json
```

Each packet binds one frozen arm to its case prompt, setup, oracle, allowed and
forbidden context, full commit, planned runtime/model, result fields, and the
cohort/fixture/runbook SHA-256 values. `manifest.json` pins every generated
packet. The authorization flags remain embedded and false; packet generation
also embeds the approved overlay and its SHA-256. The cohort's original false
flags remain visible as `frozen_preparation_boundary`; they describe the freeze
slice and are not rewritten. An absent, expired, incomplete, or mismatched
receipt fails closed before any packet is written.

Place one exact-schema result object per file in a separate directory, then run:

```bash
python scripts/evaluate_layered_harness_ablation.py evaluate \
  --results-dir /tmp/lha-results
```

Exit status is `0` only for `proceed`, `1` for a valid `modify` or `stop`
aggregate, and `2` for fail-closed input/integrity rejection. Duplicate JSON
keys, duplicate or missing arms, unexpected fields, frozen identity drift,
mutated runtime assignment, and contamination are rejected. Failed and
safe-stopped executed arms remain valid denominator records. Missing provider
tokens remain JSON `null`; they disable only the corresponding token claim.

`loaded_skill_bytes` is reported as supporting context only. A `proceed`
recommendation requires a strict improvement in a fully observed runtime-cost
metric and cannot be produced by Skill-byte reduction alone.

## Frozen aggregate cost interpretation

For each runtime-cost metric, strict improvement compares the sum of all eight
treatment arms with the sum of all eight baseline arms. The metric is eligible
only with complete paired coverage; provider-token `null` values therefore
block only that token metric's aggregate claim. Worsening tolerance is checked
per pair, so an improvement in one case cannot hide a beyond-tolerance increase
in another. `loaded_skill_bytes` uses the same aggregate reporting shape but is
never eligible to satisfy the runtime improvement gate.
