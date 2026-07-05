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
| Schema metadata behind applied migrations | `pcl migrate status --json` reports `metadata_schema_version` lower than `max_applied_version`, `consistent: false`, and no pending migrations | Run `pcl migrate --root <project>` to repair metadata only. This appends `schema_metadata_repaired` and applies no DDL. |
| Database ahead of binary | `pcl migrate status --json` warns that applied migrations or metadata are newer than the running binary | Upgrade `pcl`; do not run `pcl migrate` with the older binary. Read-only diagnostics can still be used. |
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

### Schema Metadata Repair

If an older `pcl` binary runs `pcl migrate` against a newer database, it must
not lower `metadata.schema_version`. A known failure mode is:

- `schema_migrations` contains applied rows through version 4;
- `metadata.schema_version` says `3`;
- `pcl migrate status --json` has `pending: []` but `consistent: false`.

This means the schema has already been applied and only the metadata stamp is
behind. Read-only commands diagnose this state but do not repair it:

```bash
pcl migrate status --json
pcl validate --strict --json
```

When `pending` is empty and metadata is behind the max applied migration, run:

```bash
pcl migrate --root <project>
```

The command repairs `metadata.schema_version` upward to the applied migration
version, appends a `schema_metadata_repaired` event, and prints that this was a
metadata repair, not a schema migration. It does not apply DDL.

If status says the database is ahead of the running binary, upgrade `pcl`
before running `pcl migrate`. The migrate command refuses that state to prevent
another downgrade attempt.

## Do Not Repair By Hand

Do not edit `.project-loop/project.db` directly.
Do not edit `.project-loop/events.jsonl` directly.
Do not edit `.project-loop/dashboard/dashboard.html` directly.
Do not read or parse `.project-loop/dashboard/dashboard.html` as project state.
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
