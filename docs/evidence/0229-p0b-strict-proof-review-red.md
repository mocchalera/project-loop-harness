# P0-B strict current-proof review RED evidence

Date: 2026-07-30

Base:
`7de0c7c49065cffba8ff45ef50d8cdd02e802c0a`

Independent review:
`1230d59b`

## Fail-first command

```text
PYTHONPATH=src pytest -q \
  tests/test_task_terminal_guard.py::test_coherent_copied_proof_substitution_blocks_direct_done_without_mutation \
  tests/test_task_terminal_guard.py::test_coherent_copied_proof_changes_digest_with_unchanged_hwm_across_views \
  tests/test_task_terminal_guard.py::test_coherent_evidence_set_substitution_blocks_direct_done_without_mutation \
  tests/test_task_terminal_guard.py::test_standalone_done_ignores_unrelated_active_evidence_warning_without_duplicate \
  tests/test_finish.py::test_finish_rejects_coherent_proof_substitution_before_terminal_artifacts
```

Result at the unmodified implementation:

```text
5 failed in 3.26s
```

## Reproduced defects

- A copied acceptance Evidence file and its manifest were rewritten to new,
  mutually consistent bytes/hash/size without recording an event. The public
  strict resolver reported `strict_manifest_event_mismatch`, but direct Task
  done returned exit 0 and committed the Task/event/outbox/tail.
- Task read after that substitution retained both the event HWM and
  `evaluation.input_sha256`; read/list/next remained terminally allowed.
- A current Test Evidence Set artifact was coherently redirected to an
  equivalent copied work root. Its strict resolver detected the immutable
  event hash mismatch, while direct Task done still returned exit 0.
- The same coherent copied-Evidence substitution during finish checks returned
  exit 0 with `COMPLETED_VERIFIED`, one completion-check Evidence, one packet
  Evidence/file, and a done Task.
- A standalone Task plus one unrelated active copied-Evidence hash warning
  received duplicate `evidence_adhoc_copy_hash_mismatch` reasons: manual
  `blocked` and formal `risk`. Direct done returned exit 1 despite the approved
  standalone-Evidence boundary.

The failures establish that the pre-existing GREEN suite did not prove strict
event-anchor binding or the standalone warning boundary. No production source
change was present when this RED result was captured.
