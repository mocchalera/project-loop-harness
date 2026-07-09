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
