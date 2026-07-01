# Recovery Playbook

This playbook is for operators when Project Loop Harness stops, reports validation errors, or looks out of sync.

The source of truth is `.project-loop/project.db` plus `.project-loop/events.jsonl`. The dashboard and reports are generated review artifacts.

## First Diagnostics

Run these commands from the project root:

```bash
pcl validate --strict --json
pcl report validation --strict
pcl next --strict --json
pcl loop status --json
```

Use `pcl render --json` only after normal validation passes and you want to refresh generated dashboard artifacts.

## Routing Rule

`pcl next --strict --json` routes strict validation failures before normal work. If it returns `resolve_validation_errors`, do not continue the workflow just because `pcl next --json` has a normal action.

Expected strict failure shape:

```json
{
  "type": "resolve_validation_errors",
  "command": "pcl report validation --strict",
  "blocking": true,
  "requires_human": true,
  "safe_to_run": true
}
```

The next safe action is to read `.project-loop/reports/validation-strict.md` and decide whether the issue can be resolved through existing lifecycle commands.

## Recovery Classes

| Class | Typical signal | Safe response |
|---|---|---|
| Generated artifact staleness | Dashboard or report is old, but `pcl validate --json` passes | Run `pcl report ...` or `pcl render --json` again. |
| Lifecycle state gap | An active or terminal record is missing a required transition | Use the appropriate lifecycle command if the entity is still in a valid source state. |
| Evidence or verification gap | A closed goal, passed run, or closed defect lacks required evidence | Add real evidence through the matching command path before terminal closure; do not invent evidence after the fact. |
| Duplicate active workflow runs | Strict validation reports duplicate active runs for one goal or defect | Cancel the incorrect run with `pcl loop cancel WR-0001 --summary "..."`, then rerun strict validation. |
| Audit-log integrity failure | DB and `events.jsonl` disagree, JSONL is invalid, or event order differs | Stop normal work, preserve both files, and escalate for human maintenance. |
| Repeated workflow failure | The same run or defect repair keeps failing | Open an escalation instead of retrying indefinitely. |

## Safe Repairs

Use `pcl` commands for state changes:

```bash
pcl loop cancel WR-0001 --summary "Duplicate run cancelled after validation review"
pcl jobs cancel J-0001 --summary "Superseded by newer run"
pcl defect fix D-0001 --summary "Fixed" --evidence "Commit and test evidence"
pcl verification record --run WR-0001 --result approved --reason "Reviewed repair"
pcl escalation open --severity high --question "What recovery decision is needed?" --recommendation "Preserve state and choose the least destructive repair"
```

After any repair:

```bash
pcl validate --json
pcl validate --strict --json
pcl render --json
```

## Do Not Repair By Hand

Do not edit `.project-loop/project.db` directly.
Do not edit `.project-loop/events.jsonl` directly.
Do not edit `.project-loop/dashboard/dashboard.html` directly.
Do not delete `.project-loop/reports/validation-strict.md` to hide a failure.
Do not synthesize evidence for a terminal state that was not actually verified.

If existing CLI commands cannot move the state safely, open an escalation while normal validation still allows mutation. For audit-log integrity failures, preserve the files first and avoid additional mutations until a human chooses a maintenance plan.

## Evidence Packet For Human Review

When escalation is needed, include:

- output of `pcl validate --strict --json`;
- `.project-loop/reports/validation-strict.md`;
- output of `pcl next --strict --json`;
- output of `pcl loop status --json`;
- relevant goal, run, defect, escalation, or decision report;
- `git status --short` and the latest relevant commit id;
- a short statement of which repair commands were attempted.

## Continue Criteria

Resume normal work only when:

- `pcl validate --json` passes;
- `pcl validate --strict --json` passes when strict integrity matters for the handoff;
- open escalations or decisions have been resolved or cancelled;
- `pcl next --strict --json` no longer returns `resolve_validation_errors`;
- generated dashboard artifacts have been refreshed with `pcl render --json`.
