# 0219 P0-5b Immutable Finish-Check Reuse Validation

## Scope

- Goal: `G-0069`
- Task: `T-0146`
- Feature: `F-0075`
- Story: `US-0073` (`draft`)
- Tests: `TC-0159`–`TC-0162` (`planned`)
- Implementation commit: `230a454`

This slice executes equivalent configured finish-check roles once per
invocation and incorporates only compatible immutable historical results into
stability evaluation. It does not approve the Story, pass the PCL Tests,
claim a warm-cache attempt, enforce stability as a terminal prerequisite,
migrate the database, or add dependencies.

## Contract

- Equivalent checks are coalesced by role-neutral scope, kind, and guarded
  execution argv. Stable role bindings retain every original check ID and
  configuration key.
- Each invocation still performs one fresh guarded execution. Historical
  Evidence supplements stability; it never replaces the fresh run.
- `verification-execution-identity/v1` excludes role names and cold/warm
  labels but binds the input manifest, lock inputs, argv, toolchain, platform,
  environment digest, timeout, output bound, and normalized execution policy.
- A prior result is accepted only through an exact target
  `verification_check` link and a `completion_packet_created` or
  `finish_attempt_recorded` event containing its Evidence ID and exact
  artifact SHA-256.
- The canonical result path, regular-file/no-symlink boundary, artifact bytes,
  `finish-check-result/v2`, Evidence ID, assertion shape, and execution
  identity must all agree.
- Candidate scans are bounded to 100 exact-target rows and stability uses at
  most two prior attempts. Rejection counts remain visible.
- Distinct commands execute independently. Single-role check-plan fields and
  `completion-packet/v1` remain backward compatible; reuse information is
  additive.
- Existing P0-3 terminal-readiness consumes the resulting stability evaluation
  unchanged. Cold-only history remains `reproducible: false`.

## Fail-first

```text
PYTHONPATH=src pytest -q tests/test_finish.py \
  -k 'equivalent_roles or compatible_hash_anchored or history_rejects_tampered or distinct_roles'

4 failed, 22 deselected in 8.38s
```

The failures showed both duplicate role executions and the absence of reuse
receipts, artifact anchors, and compatible history.

## Green verification

```text
PYTHONPATH=src pytest -q tests/test_finish.py \
  -k 'equivalent_roles or compatible_hash_anchored or history_rejects_tampered or distinct_roles'

4 passed, 22 deselected in 10.01s
```

```text
PYTHONPATH=src pytest -q tests/test_verification_results.py tests/test_finish.py

37 passed in 25.81s
```

```text
PYTHONPATH=src pytest -q tests/test_finish.py \
  tests/test_verification_results.py tests/test_terminal_readiness.py \
  tests/test_workflow_sandbox.py tests/test_contract_cli.py

80 passed in 26.50s
```

```text
PYTHONPATH=src pytest -q

1226 passed, 1 skipped in 341.07s (0:05:41)
```

```text
PYTHONPATH=src python -m ruff check \
  src/pcl/check_result_reuse.py src/pcl/verification_results.py \
  src/pcl/finish_execution.py tests/test_finish.py

All checks passed!
```

`git diff --check` and Python bytecode compilation passed.

## Temporary-project dogfood

An isolated Git project at `/tmp/pcl-p05b-dogfood.CtIWU4` was initialized with
the current worktree source. Its `lint` and `test` roles both used:

```text
python -m pytest -q test_sample.py
```

Observed behavior:

- the public check plan contained one execution and two stable role bindings;
- the first fresh result was Evidence `E-0002` with an event-bound artifact
  SHA-256;
- the second invocation executed once, accepted `E-0002` as compatible cold
  history, and reported `attempt_count: 2`;
- after changing the prior artifact bytes and invoking with timeout 121, no
  history was accepted and the bounded rejection receipt reported
  `artifact_hash_mismatch: 1` and `execution_identity_mismatch: 1`;
- all cold attempts remained `reproducible: false`.

The dogfood also found a separate existing finish-effect issue: pytest created
a root-level `__pycache__` artifact that matched the declared output patterns
but was classified as `mutates_inputs`. It is recorded separately as Gap
Report Evidence `E-0608`; this milestone does not hide or repair it.

## Residual boundaries

- Reuse is deliberately target-local and bounded. It does not aggregate across
  Tasks or Goals.
- A fresh execution remains mandatory, so this slice removes duplicate roles
  and enriches stability history rather than providing a cache-only finish.
- Warm-cache execution is not yet trustworthy in the isolated workspace and
  is not synthesized. Cold-only consecutive passes cannot set
  `reproducible: true`.
- Event payload hashes anchor newly emitted results. Legacy results without
  these additive anchors are rejected rather than inferred.
- Story `US-0073` remains draft and Tests `TC-0159`–`TC-0162` remain planned;
  implementation authorization is not semantic approval.
- Task-to-Feature relation repair remains a separate PCL routing/readiness
  friction. The implementation does not create a second relation mechanism.
