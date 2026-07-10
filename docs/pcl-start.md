# `pcl start` lite entry point

`pcl start "<intent>"` creates the smallest work target that the current
Project Loop state machine can route: one open Goal and one linked todo Task.
It does not call an LLM, infer acceptance criteria, launch an agent, or execute
the intent as shell text or a path.

## Commands

```bash
pcl start "Fix login timeout"
pcl start "Fix login timeout" --dry-run
pcl start "Fix login timeout" --no-init
pcl start "Separate follow-up" --new
pcl start "Fix login timeout" --json
```

`--profile` is intentionally unsupported until route and policy work lands in
Wave C. Existing Goal, Task, and Workflow commands remain unchanged.

## Initialization and duplicate behavior

Running `start` in an uninitialized directory is an explicit request to perform
the existing safe initialization flow. Existing project files are preserved;
`--dry-run` returns every planned init change and planned state entity without
creating the target directory, database, event, or file. `--no-init` instead
returns the existing `not_initialized` error with exit code 3.

In an initialized project, any nonterminal Goal or Defect, or any queued,
running, or blocked workflow run, counts as active work. Without `--new`,
`start` returns `active_work_exists`, creates nothing, and points to the action
selected by the existing `pcl next` router. `--new` is the explicit override
for creating a separate Goal and Task.

Goal + Task is used instead of Task alone because current task routing joins a
Task to an open or active Goal. An orphan Task would exist in storage but would
not become the active `pcl next` target.

## JSON contract

The command response uses `pcl-start/v1`:

```json
{
  "command": "start",
  "contract_version": "pcl-start/v1",
  "mutated": true,
  "status": "started",
  "result": {
    "intent": "Fix login timeout",
    "project_initialized": true,
    "created_ids": {
      "goal": "G-0001",
      "task": "T-0001",
      "evidence": "E-0001",
      "event": "EV-..."
    },
    "target": {"type": "task", "id": "T-0001"}
  },
  "warnings": [],
  "next_actions": [
    {
      "text": "Review the task context and begin the requested work.",
      "command": "pcl context pack --task T-0001 --json",
      "target": {"type": "task", "id": "T-0001"}
    }
  ]
}
```

`status` is `planned`, `started`, `active_work_exists`, or `init_blocked`.
JSON mode writes exactly one JSON document to stdout and never prompts for
confirmation.

Successful creation also records `start-receipt/v1` as inline Evidence and a
`work_started` event through the normal mutation transaction and JSONL outbox.
The receipt preserves the intent literally and records actor `pcl:start`, Git
HEAD when available, the Goal and Task IDs, and the active Task target. The
contract is deliberately small so future Work Brief and route fields can be
added without changing the lite behavior.
