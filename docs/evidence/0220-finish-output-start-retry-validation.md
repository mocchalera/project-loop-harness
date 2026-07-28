# 0220 P0-5c Finish Output / Start Retry Validation

## Scope

- Goal: `G-0070`
- Task: `T-0147`
- Feature: `F-0076`
- Stories: `US-0074`–`US-0075` (`draft`)
- Tests: `TC-0163`–`TC-0167` (`planned`)
- Implementation commit: `1b45260`

This slice bounds the display projection of `finish --emit-packet --dry-run`
and makes an exact explicit `start --task` retry idempotent. It does not
approve either Story, mark the PCL Tests passing, weaken the complete
repository snapshot, migrate the database, add dependencies, or change
target-unspecified `start` behavior.

## Contract

### Finish dry-run output

- The default packet dry-run keeps its existing JSON shape.
- `--summary`, `--output-offset`, `--output-limit`, and
  `--exclude-machine-state` are accepted only with
  `--emit-packet --dry-run`.
- Summary and pagination are mutually exclusive. Offset is non-negative and
  limit is bounded to `1..500`; invalid combinations fail before mutation.
- `finish-output-projection/v1` reports full, eligible, returned, omitted, and
  next-page counts.
- Machine-state exclusion is a display-only projection for the documented
  `.claude/`, `.codex/`, `.playwright-cli/`, and `.work/` prefixes.
- `repository.dirty`, `repository.diff_sha256`, target binding, terminal
  readiness, and verification inputs remain computed from the complete
  snapshot.

### Explicit Task start retry

- The first explicit `start --task` request records the normal receipt,
  `work_started` event, Evidence, and optional Skill execution provenance.
- `start-retry-identity/v1` binds literal intent, exact Task, Git HEAD, and
  ordered Skill name/path-scope/content hashes.
- Only the latest exact Task start receipt is eligible for reuse.
- The receipt Evidence, event payload, target, repository revision, and Skill
  provenance artifact are revalidated before reuse.
- Exact retry returns `already_started`, `mutated: false`, empty
  `created_ids`, and additive `reused_ids`.
- Changed intent, HEAD, or Skill hash records a new receipt. Legacy,
  malformed, missing, or inconsistent anchors are not inferred.
- Unbound and new-work start responses preserve the prior public JSON shape;
  request identity is additive only on explicit Task attach receipts.

## Fail-first

```text
PYTHONPATH=src pytest -q tests/test_finish.py tests/test_start.py \
  -k 'output_projection or active_task_exact_retry or retry_identity_covers'

7 failed, 42 deselected in 2.32s
```

The failures showed that finish projection flags did not exist and repeated
explicit Task attach created duplicate Evidence/events without a bound request
identity.

## Green verification

```text
PYTHONPATH=src pytest -q tests/test_finish.py -k 'output_projection'

5 passed, 26 deselected in 1.76s
```

```text
PYTHONPATH=src pytest -q tests/test_start.py -k 'retry'

4 passed, 16 deselected in 1.06s
```

The retry tests include exact reuse, changed intent/HEAD/Skill identity,
corrupted Evidence anchors, and a missing receipt anchor.

```text
PYTHONPATH=src pytest -q tests/test_finish.py tests/test_start.py

51 passed in 31.71s
```

```text
PYTHONPATH=src pytest -q tests/test_execution_provenance.py \
  tests/test_contract_cli.py tests/test_cli_init.py \
  tests/test_target_resolver.py tests/test_finish.py tests/test_start.py

117 passed in 32.84s
```

```text
PYTHONPATH=src pytest -q

1235 passed, 1 skipped in 380.03s (0:06:20)
```

```text
PYTHONPATH=src python -m ruff check .

All checks passed!
```

`git diff --check` passed.

## Repository dogfood

The default `finish` dry-run for `T-0147` returned 247 change rows and two
harness-local rows with:

```text
dirty: true
diff_sha256: sha256:561835c0f87682f7da4612332915e46a7849998ef5df4a5a9a70653a47338edc
```

Summary plus machine-state exclusion returned zero rows, retained the same
dirty bit and digest, and reported:

```text
eligible changes: 8 / total 247
omitted: 239
.claude/: 229
.playwright-cli/: 2
.work/: 8
```

An offset-1/limit-1 page returned one eligible repository change and one
harness-local row while retaining the same complete snapshot identity.

The first exact active-Task attach with the repository
`project-control-loop` Skill created:

```text
Evidence: E-0611
provenance Evidence: E-0612
event: EV-487A4441963F
request identity: sha256:198cc8ead43a3194faafccc5e5bf5d7760b4928bb544375a30693a2df1e708c2
```

The identical retry returned `already_started`, `mutated: false`, reused
`E-0611` and `EV-487A4441963F`, and reused the validated `E-0612` provenance.
Audit projection remained aligned at 2104 SQLite/JSONL events with zero
pending, failed, or retry-wait outbox records.

## PCL validation

- strict validation: zero errors, three active and 26 historical advisories;
- dashboard render: success;
- audit check: 77 pre-existing human-review Evidence reconciliation findings,
  zero repairable/unsupported findings, and no outbox projection backlog.

The existing advisories and historical reconciliation findings were not
normalized or repaired by this slice.

## Residual boundaries

- Machine-state exclusion reduces display volume; it is not an input
  sandbox, ignore rule, or permission boundary.
- A single offset/limit is applied independently to the repository-change and
  harness-local sections. Independent section cursors are not introduced.
- Idempotency is deliberately limited to explicit active-Task attach and the
  latest exact anchored receipt. A legacy active Task gets one new
  identity-bearing receipt before subsequent exact retries can reuse it.
- A new Git commit changes the request identity even when intent and Skills
  are unchanged.
- Story approval and PCL Test result transitions remain human-controlled.
- The separate root-level `__pycache__` finish-effect issue remains tracked by
  Gap Report Evidence `E-0608`.
