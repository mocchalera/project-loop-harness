# P1-A Direct Setup verification evidence

Date: 2026-07-30
Implementation commit: `5f3b12fa04a4b18217f7c95d67c5fcb74b203228`

## Immutable contract disposition

The implementation follows the confirmed design from Cockpit task `b8dd2cd6`
and the independent High 0 / Medium 0 review from task `0716f0b4`. The user's
final tail decision supersedes the reviewed staged-renderer proposal:
validation and routing are read-only for canonical dashboard artifacts; the
current canonical renderer is called at most once, inside the exclusive
project-operation lock, and only after the HWM recheck matches.

Schema remains 8 and `pyproject.toml` still has an empty runtime dependency
list. No P1-B terminal acceptance or P1-C Skill router was added.

## Automated verification

```text
PYTHONPATH=src python -m pytest -q \
  tests/test_direct_setup.py \
  tests/test_mutation_tail.py \
  tests/test_start.py \
  tests/test_event_outbox.py \
  tests/test_validation.py \
  tests/test_validation_p0b.py \
  tests/test_validation_p1.py \
  tests/test_validation_p1_strict.py \
  tests/test_validation_p1_5.py \
  tests/test_validation_p3.py \
  tests/test_command_guide.py \
  tests/test_cli_init.py
165 passed in 23.69s

PYTHONPATH=src python -m pytest -q
1365 passed, 1 skipped in 346.20s (0:05:46)

PYTHONPATH=src python -m ruff check .
All checks passed!

git diff --check
exit 0
```

The full suite includes atomic rollback at each bundle event boundary,
same-request and different-request concurrency, malicious JSON, nested
duplicate keys, descriptor/path swaps, deterministic-anchor collisions,
receipt tampering and compatibility, pre-existing/persisted projector pending
states, late HWM drift, stable validation failure, renderer failure, legacy
start parity, and P0-B terminal-readiness non-bypass.

## Public surface and Skill parity

`PYTHONPATH=src python -m pcl start --help` preserves the legacy `--goal`,
`--task`, and `--skill` options and adds `--direct-spec DIRECT_SPEC`.

All four Project Control Loop Skill copies have this SHA-256:

```text
675395adc8e7601096f92dbbe208168e7521d97139fd714afce6014cb66d679e
```

## Fresh initialized-project smoke

Root: `/tmp/pcl-direct-smoke.Y8v7Ew`

- `pcl init --target ... --json`: `created=true`, `event_appended=true`
- first valid Direct call: `status=started`; Goal `G-0001`, Task `T-0001`,
  Feature `F-0001`, Story `US-0001`, Test `TC-0001`, Evidence `E-0001`;
  anchor `EV-EFDF0B526E43`; bundle sequence 10-17, count 8; Story remained
  `draft`, Test remained `planned`; tail was stable and rendered
- exact retry: `status=already_started`, `mutated=false`; the same IDs were
  reused; tail `not_changed`; renderer `not_changed`
- same request with changed Feature description: exit 1,
  `direct_setup_idempotency_conflict`
- `pcl validate --strict --json`: exit 0, `ok=true`, zero findings
- `pcl audit check --json`: exit 0, `status=clean`, 17 DB events, 17 JSONL
  events, 17 delivered outbox rows, zero anomalies
- `pcl render --json`: exit 0, `ok=true`
- `pcl doctor --json`: exit 0, `ok=true`, with the three expected fresh-template
  configuration warnings

`doctor --strict` intentionally returned exit 1 because the untouched fresh
template still has `project.name=CHANGE_ME`, empty command slots, and no finish
checks. Those configuration warnings are unrelated to Direct Setup integrity;
the strict state validator and audit check both passed.

## Honest residual boundary

The tests verify fail-closed behavior and renderer error paths, but do not claim
cross-platform secure-open acceptance or two-file/process-crash dashboard
atomicity. No success receipt or hashes are reported for partial render
failure.
