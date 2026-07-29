# Task terminal-readiness/v1

`terminal-readiness/v1` is the shared, additive proof receipt used by Task
read/list/next, direct `pcl task status ... done`, and Task-bound `pcl finish`.
It does not add a database table or weaken Feature, Evidence, Workflow, Goal,
human-approval, or completion-packet contracts.

## Authoritative transition

`pcl task status T-XXXX done --reason ...` opens the existing
`connect_mutation()` transaction (`BEGIN IMMEDIATE`), resolves the exact Task
through `routing-target/v1`, and re-reads all proof inputs in that transaction.
An already-`done` Task returns the existing `changed=false` result before
preflight; other statuses retain their existing behavior.

A changed transition to `done` requires:

- every dependency to be terminal;
- a related Feature, when present, to be `done` rather than merely
  `ready_to_close`;
- approved/waived Stories, passing/waived Tests, and no active Defects for that
  Feature;
- the Feature's newest exact-target acceptance Evidence to be current,
  supported, non-superseded, and healthy;
- direct Test Evidence or Evidence Set and its completion-policy receipt to be
  healthy and target-bound;
- Workflow-backed Tests to use the Task Goal, a passed Run, passed Jobs, and an
  approved Verification;
- a non-contradictory Goal with a valid, non-exhausted budget and no exact-scope
  open Decision or Escalation;
- no current exact-proof or global active error, unknown/unsupported finding,
  or human-required gate.

A standalone Task gains no new Evidence prerequisite. Its dependencies, Goal,
formal findings, and human gates still apply.

## Finding scope and ordering

Formal findings reuse strict validation and validation-projection scope rules.
Current exact-proof findings are re-evaluated and block. Superseded historical
Evidence outside the current proof closure is advisory. A historical Evidence
ID still referenced by the current closure blocks. Global active errors,
unknown/unsupported findings, and human-required findings always block.

Reasons are normalized, exactly deduplicated, and sorted by:

1. `blocked`;
2. `incomplete`;
3. `risk`;
4. `advisory`;
5. code and canonical details.

`next_commands` preserves that reason order while deduplicating exact commands.

## Snapshot receipt

The additive Task receipt includes:

```json
{
  "contract_version": "terminal-readiness/v1",
  "target": {"type": "task", "id": "T-XXXX"},
  "transition": {"from_status": "in_progress", "to_status": "done"},
  "status": "ready",
  "terminal_allowed": true,
  "reasons": [],
  "next_commands": [],
  "evaluation": {
    "source": "task_status",
    "evaluated_through_event_sequence": 42,
    "evaluated_through_event_id": "EV-XXXXXXXXXXXX",
    "input_sha256": "sha256:...",
    "finding_counts": {"active": 0, "historical": 0}
  }
}
```

The canonical input digest excludes presentation-only `source` but includes
the exact Task, dependency, Feature/Story/Test/Defect, Evidence, Workflow,
Goal, Decision/Escalation, formal-finding, Evidence-health, and event
high-watermark inputs. Read/list/next/direct surfaces therefore expose the same
digest for the same database snapshot.

## Failure and commit boundary

If direct preflight is not terminally allowed, the command returns exit 1 and
typed `task_terminal_readiness_failed`. It rolls back without changing the
Task row, event table, outbox, `events.jsonl`, dashboard artifacts, or invoking
`mutation-tail/v1`.

Only success writes one Task update and one `task_status_changed` event/outbox
pair. The identical readiness receipt is returned in the result and stored in
the event payload. The P0-A next-action/render tail starts only after that
authoritative commit.

Task-bound `finish` records the pre-check receipt, runs checks, then re-resolves
the Task and re-evaluates readiness in its final `BEGIN IMMEDIATE`. A changed
Task status, event high-watermark, canonical input digest, or newly blocked
receipt returns exit 1 and typed `finish_target_readiness_changed` before
completion-check Evidence, packet files, packet Evidence, or Task terminal
events are created. Ordinary failed checks retain the existing incomplete
attempt/packet behavior.
