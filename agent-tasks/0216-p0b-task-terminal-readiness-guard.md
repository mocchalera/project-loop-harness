# 0216: P0-B Task terminal readiness guard

- **Status:** Remediated locally; independent re-review pending
- **Milestone:** P0-B terminal mutation safety
- **Priority:** P0
- **Size:** L
- **Dependency:** P0-A mutation-tail commits through `c923a1e`
- **Project Loop:** Goal `G-0002`, Task `T-0002`, Feature `F-0002`, Story
  `US-0002`, Tests `TC-0014`–`TC-0019`
- **Schema/dependencies:** unchanged

## Approved contract

Cockpit Ask `ask_adc40334f575` fixed these semantics:

1. A Task related to a Feature requires that Feature to be `done` with healthy
   acceptance Evidence; `ready_to_close` is insufficient.
2. A standalone Task receives no new Evidence requirement.
3. Findings use current proof closure. Historical findings outside it are
   advisory; historical proof still referenced by the current closure is
   rechecked and blocks. Global active error, unknown, and human-required
   findings block.

## Implementation

- Direct Task `done` evaluates one deterministic `terminal-readiness/v1`
  receipt after exact target resolution in the existing `BEGIN IMMEDIATE`.
- Failure is typed exit 1 and zero-mutation across Task/event/outbox/JSONL and
  dashboard bytes. It does not call the P0-A mutation tail.
- Success records exactly one status event/outbox and stores the same receipt
  in the result and event before the post-commit P0-A tail.
- Task read/list/next/direct share the same event HWM and canonical input
  digest.
- Task-bound finish compares the pre-check Task/HWM/input receipt with a fresh
  final-transaction receipt before creating check Evidence or packet files.
- Existing normal check-failure attempts/packets and same-state Task no-ops are
  unchanged.

## Independent review correction

Review task `1230d59b` found that current copied Evidence and Evidence Set
artifacts were assessed for self-consistency but were not included in the
canonical Task input as strict event-anchored identities. A coherent
manifest/copy or Evidence Set rewrite could therefore retain the event HWM and
digest and pass both direct done and finish. The same review found that a
standalone Task was blocked by an unrelated active Evidence warning because a
manual scan duplicated the formal risk finding as a blocker.

The remediation must reuse the existing strict resolvers in the caller-owned
snapshot, bind recording event and artifact/member hashes into the canonical
input, block strict current-proof findings before terminal artifacts, and
remove manual active-Evidence blocking outside the current proof. Formal
global error/unknown/human gates remain fail-closed; unrelated warnings remain
risks.

Independent re-review `c12dd3d9` then found that finish enabled its final
freshness comparison only when checks passed without a repository race or
mutating/unknown input effect. Evidence Set drift overlapping a repository race
therefore persisted incomplete check/packet artifacts instead of taking the
typed zero-mutation rollback. The final transaction must prioritize Task/HWM/
canonical strict-proof freshness whenever the pre-check receipt was terminally
allowed, while preserving snapshot-stable failure and race semantics.

## Verification boundary

Use source-tree execution only:

```text
PYTHONPATH=src pytest -q tests/test_terminal_readiness.py tests/test_task_terminal_guard.py
PYTHONPATH=src pytest -q tests/test_finish.py
PYTHONPATH=src pytest
PYTHONPATH=src ruff check .
git diff --check
PYTHONPATH=src python -m pcl --root . --json validate --summary
PYTHONPATH=src python -m pcl --root . --json render
```

Story `US-0002` remains draft and Tests `TC-0014`–`TC-0019` remain planned:
implementation authority and the external Ask decisions are not fabricated as
Story-approval provenance. Record immutable implementation Evidence without
closing or removing the Task.

## Stop conditions

Do not add a migration, dependency, force/override path, automatic human
approval, weakened Evidence/completion policy, push, release, publication, or
external mutation.
