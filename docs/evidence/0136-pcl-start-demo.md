# 0136 `pcl start` demo evidence

- Date: 2026-07-10
- Source: linked worktree at base `e801ef02e705c89adcc09b3292387fd47ff22331`
- Runtime: `PYTHONPATH=src python -m pcl`
- Target: fresh `/tmp/pcl-0136-demo.*` directory

## Start transcript

The implementation-start receipt was:

- target commit: `e801ef02e705c89adcc09b3292387fd47ff22331`;
- task 0134 dependency: merged as `ec57484` (`completion-packet/v1` contract),
  with follow-up hardening at the target commit;
- planned paths: `src/pcl/start.py`, `src/pcl/cli.py`, the narrow public
  next-action wrapper in `src/pcl/commands.py`, start tests/fixtures, the
  additive help snapshot, and start documentation/evidence;
- characterized reuse: `plan_init_project`/`init_project` preserve the existing
  init plan and apply behavior; `create_goal` and `create_task` each own their
  mutation event; `next_action` and `loop_status` remain the routing and active
  work sources of truth;
- out of scope: LLM calls, inferred acceptance criteria, agent launch,
  `--profile`, `resume`, and changes to existing granular commands.

Command:

```bash
/usr/bin/time -p env PYTHONPATH=src python -m pcl \
  --root "$demo" start "Fix login timeout" --json
```

Material output, with volatile event ID, timestamp, and temp suffix shortened:

```json
{
  "command": "start",
  "contract_version": "pcl-start/v1",
  "mutated": true,
  "status": "started",
  "result": {
    "created_ids": {
      "goal": "G-0001",
      "task": "T-0001",
      "evidence": "E-0001",
      "event": "EV-..."
    },
    "intent": "Fix login timeout",
    "project_initialized": true,
    "target": {"id": "T-0001", "type": "task"},
    "receipt": {
      "actor": "pcl:start",
      "contract_version": "start-receipt/v1",
      "repository_revision": null
    }
  },
  "next_actions": [
    {
      "command": "pcl context pack --task T-0001 --json",
      "target": {"id": "T-0001", "type": "task"},
      "text": "Review the task context and begin the requested work."
    }
  ],
  "warnings": []
}
```

Measured wall time:

```text
real 0.84
user 0.23
sys  0.14
```

Manual time-to-first-value is therefore **0.84 seconds** from command launch to
an initialized project, active Task ID, durable start receipt, and safe next
action on this machine. This is comfortably below the milestone's ten-minute
manual threshold; it is a local observation, not a cross-machine benchmark.

## Wedge continuation check

The current base contains the existing `finish` planner. Immediately after
`start`, `finish --json` identified open Goal `G-0001`, while `next --json`
selected Task `T-0001` and returned
`pcl context pack --task T-0001 --json`. The future read-only `resume` command
belongs to task 0137 and is not implemented by 0136, so this artifact records
the start portion of the planned start → finish → resume transcript without
claiming the later command exists.

Post-start integrity checks both exited 0:

```text
PYTHONPATH=src python -m pcl --root "$demo" validate --strict --json
{"errors": [], "ok": true, "warnings": []}

PYTHONPATH=src python -m pcl --root "$demo" audit check --json
status=clean db_events=12 jsonl_events=12 outbox_records=12 pending=0
evidence_metadata=1 evidence_mismatches=0
```
