# 0196 Active Proof / Historical Findings Verification

Date: 2026-07-18 (Asia/Tokyo)

## Responsibility map

Validation findings remain one ordered list with their existing severity,
message, entity, repair class, and suggested commands. The additive
`proof_scope` field is classified only from a current finding-code allowlist
plus durable SQLite state:

- Goal closure-proof families become historical for `closed` or `cancelled`
  Goals.
- Legacy Feature lifecycle families become historical for `done` or `waived`
  Features. `feature_done_open_defects` remains active because it identifies an
  active child contradiction.
- Test proof families become historical only when the Test is waived or its
  owning Feature is done/waived. A passing Test under an active Feature remains
  active.
- Defect terminal-proof families become historical only for closed/waived
  Defects.
- Passed Workflow Run proof families become historical only when their owning
  Goal is closed/cancelled.
- Current artifact, adhoc, and evidence-set families become historical for an
  Evidence row only when a durable `supersedes` link names its replacement.

All other families, unknown codes, missing status rows, relationship
contradictions, and unclassifiable Evidence default to active. Classification
does not inspect English messages, summaries, user intent, or repair commands.

## Additive contract

- Each structured finding includes `proof_scope: active|historical`.
- Validation JSON includes deterministic `finding_counts` with both `active`
  and `historical` keys, including when either count is zero.
- Markdown validation reports show both counts and retain one ordered findings
  table with a `proof_scope` column.
- Existing `ok`, `errors`, `warnings`, `findings`, finding codes, ordering,
  repair commands, and exit codes are unchanged.

## Verification

### Focused classification and compatibility suite

```text
PYTHONPATH=src pytest -q \
  tests/test_baseline_fixtures.py tests/test_dashboard_data_contract.py \
  tests/test_evidence_add.py tests/test_integrity_migration_dogfood.py \
  tests/test_lifecycle_integrity.py tests/test_validation_proof_scope.py

55 passed in 9.18s
```

The focused cases include active proof under a nonterminal parent, historical
terminal families, superseded Evidence, and an unknown code on superseded
Evidence that must remain active.

### Full regression suite

```text
PYTHONPATH=src pytest -q

1095 passed, 1 skipped in 219.01s
```

### Static and patch checks

```text
ruff check .
All checks passed!

git diff --check
exit 0
```

### Current-repository dogfood

The worktree runtime validated the canonical checkout read-only; output was
redirected outside the repository so no `.project-loop` artifact was changed:

```text
PYTHONPATH="$PWD/src" python -m pcl \
  --root /Users/mocchalera/Dev/project-loop-harness \
  --json validate --strict > /tmp/pcl-0196-dogfood.json
```

Result: exit 0, `ok=true`, 0 errors, 29 warnings, and
`finding_counts={"active":3,"historical":26}`. The 26 historical findings are
closed-Goal and done-Feature/Test compatibility gaps. The three active findings
are current, non-superseded Evidence drift and therefore were not downgraded.

## Limitations and residual risk

- Evidence linked only to terminal entities is not inferred historical. Without
  an explicit supersession link, another durable consumer may still rely on it,
  so it remains active.
- New finding codes remain active until their durable ownership and terminal
  semantics are explicitly reviewed and added to an allowlist.
- `proof_scope=historical` is presentation metadata only. Historical errors
  still make `ok=false` and preserve their existing exit behavior.
