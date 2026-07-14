# `pcl finish`

`pcl finish` is a terminal close-out planner for the current Project Loop
Harness loop. It reports the next ordered close-out step for the active workflow
run and its goal without asserting state on the operator's behalf.

It never completes jobs, records verifications, completes or fails workflow
runs, or closes goals. Those steps remain explicit commands in the returned
plan.

## Usage

```bash
pcl finish
pcl finish --json
pcl finish --execute
pcl finish --emit-packet --dry-run --task T-0001 --json
pcl finish --emit-packet --task T-0001 --base HEAD --json
pcl finish --run WR-0001 --json
pcl finish --goal G-0001 --json
```

By default, `finish` targets the newest active workflow run, using the same
active-run lifecycle ladder as `pcl next`. If no active run exists, it falls
back to the newest open goal. If neither exists, it returns a finished
nothing-to-do payload.

## JSON Payload

```json
{
  "ok": true,
  "finish": {
    "target": {"run": "WR-0001", "goal": "G-0001"},
    "finished": false,
    "remaining_steps": [
      {
        "type": "record_verification",
        "command": "pcl verification record --run WR-0001 --result approved --reason 'Summarize verification evidence'",
        "reason": "All active workflow jobs are terminal, but no approved verification exists.",
        "requires_human": true,
        "safe_to_run": false
      }
    ],
    "next_command": "pcl verification record --run WR-0001 --result approved --reason 'Summarize verification evidence'"
  }
}
```

With `--execute`, the payload also includes:

```json
{
  "executed": [
    {"command": "pcl validate --strict", "ok": true},
    {"command": "pcl render", "ok": true}
  ],
  "changed": true
}
```

## Execute Boundary

`pcl finish --execute` runs nothing while any finish step remains. This includes
safe read steps such as `pcl jobs read ...`, because the loop is not terminal
yet.

Only when `remaining_steps` is empty does `--execute` run the generation tail:

```bash
pcl validate --strict
pcl render
```

The command does not run `pcl report`, does not record verification, and does
not close goals. Operators run the planned commands themselves after reviewing
the state and evidence.

## Completion packet mode

`--emit-packet` is a separate, explicit execution mode. It does not change the
default planner and it does not change `--execute`. The two execution flags are
mutually exclusive. `--dry-run` previews the selected target, Git snapshot,
changed paths, and guarded check plan without executing commands or mutating
Project Loop state.

In non-interactive use, invoking `--emit-packet` without `--dry-run` is the
operator's confirmation to run the displayed project-configured check plan.
There is no prompt and no implicit arbitrary command. The plan contains only
enabled `pcl.yaml` entries from `commands.lint`, `typecheck`, `test`, `e2e`,
and `build`, in that order. Commands that do not apply may be marked explicitly
with `null`, `{disabled: true}`, or a nested `disabled: true`. Empty values
remain configuration warnings. `pcl start` and `pcl doctor` report an actionable
warning when no finish check is enabled, and packet emission returns the typed
`finish_checks_not_configured` error before repository inspection.

Every enabled command must pass the guarded-executor allowlist. The exact argv
`git diff --check` is accepted as a read-only whitespace check; other `git`
forms remain blocked. Missing checks or a blocked configured check return exit
2 before execution.

`--task` selects a task directly. Existing `--goal` and goal-backed `--run`
targets are also accepted. Without an explicit target, packet mode uses the
normal finish goal target first, then the highest-priority active task. A run
without a goal cannot be represented by `completion-packet/v1` and is rejected.

### Repository snapshot and race guard

`--base <revision>` selects the Git base; the default is `HEAD`. The producer
records the resolved base and head commit IDs, repository dirty state, changed
paths, and a deterministic diff hash. The hashed bytes are the exact output of
`git diff --binary --no-ext-diff <resolved-base> --` excluding
`.project-loop/**`, followed by sorted, length-prefixed path/content records for
Git-unignored untracked files. PCL-owned files under `.project-loop/**` are
reported separately as `harness_local_state`; they do not turn a clean
repository result into `COMPLETED_WITH_RISK`.

The snapshot is captured before checks and again afterward. Any base, head,
dirty-state, changed-path, or diff-hash change yields
`INCOMPLETE_VALIDATION`; finish records the check Evidence and packet but does
not complete the target.

### Timeout recovery

When a guarded finish check reaches the per-check timeout, the JSON result adds
`timeout_recovery`. For a timeout below the guarded executor ceiling, it names
one exact retry command for the same target with `--timeout 600 --json`.
The incomplete completion packet stores the same command in `next_action`, so a
subsequent `pcl next --json` preserves the recovery route for an agent.

PCL does not run this retry automatically and does not change `pcl.yaml`. If a
check times out at the 600-second ceiling, the recovery instead points to the
timed-out check Evidence. `pcl next` then recommends diagnosis rather than the
same ineffective retry. In both cases the packet outcome remains
`INCOMPLETE_VALIDATION` until a later explicit finish run passes.

### Evidence and commit boundary

Each check uses the host guarded executor with argv execution, fixed project
root, environment allowlist, bounded stdout/stderr, and redaction. Its result
JSON and redacted streams are recorded as Evidence. The validated packet is
stored under `.project-loop/evidence/completion-packets/` by its content hash.

Check Evidence rows, packet Evidence/reference, a successful task transition,
and events commit in one `BEGIN IMMEDIATE` transaction through the service
layer and transactional outbox. A projector failure returns recoverable exit
6: do not retry; run `pcl audit flush --json`. If a packet file was finalized
but the SQLite commit did not occur, `pcl audit check` reports
`orphan_completion_packet` for human review.

The read-only [`pcl resume`](handoff-packet-v1.md) surface consumes the newest
valid completion packet through its target-bound `completion_packet` Evidence
link. It preserves the packet's verified/unverified boundary and does not alter
finish state. Reproducible check commands are copied into restart context as
replay instructions with their previous packet status; resume does not execute
them. Their Evidence metadata can be resolved without reading artifact bodies
with `pcl evidence show E-XXXX --json`.

### Outcomes and exits

- `COMPLETED_VERIFIED`: configured checks and strict validation pass, the
  snapshot is stable, changes exist, and no gate blocks completion. A task
  transitions to `done` in the packet transaction.
- `COMPLETED_WITH_RISK`: the completed conditions hold but strict validation
  returned warnings; the warnings are packet risks.
- `INCOMPLETE_VALIDATION`: a check or strict validation fails, or the repository
  changes during checks. The packet is retained, the target stays active, and
  the command exits 1.
- `INCOMPLETE_HUMAN_DECISION_REQUIRED`: a linked open decision or an existing
  human-required finish step blocks completion. The target stays active.
- `INCOMPLETE_BUDGET_EXHAUSTED`: the target goal has explicit
  `budget_json.exhausted: true`. The target stays active.
- `NO_CHANGES`: the captured change list is empty. Checks are still recorded,
  but the task stays active because repository acceptance Evidence was not
  established.

Successfully emitted incomplete/no-change packets return a normal JSON payload;
only `INCOMPLETE_VALIDATION` uses exit 1. Usage and unsafe-plan errors use exit
2. Repeating packet mode for an unchanged terminal target and repository
snapshot returns the existing packet with `idempotent: true`, `changed: false`,
and does not create another completion event.
