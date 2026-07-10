# Recovery Playbook

This playbook is for operators when Project Loop Harness stops, reports validation errors, or looks out of sync.

The source of truth is `.project-loop/project.db`. `events.jsonl` is a derived,
rebuildable audit projection. The dashboard and reports are generated review
artifacts.

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
| Audit-log integrity failure | DB/outbox/`events.jsonl` disagree, JSONL is invalid, or event order differs | Stop normal work and run `pcl audit check --json`. Apply only a fully supported preview; otherwise preserve the report and use the reviewed rebuild path. |
| Repeated workflow failure | The same run or defect repair keeps failing | Open an escalation instead of retrying indefinitely. |

## Safe Repairs

### Plan lifecycle repair for existing projects

For terminal rows created before the lifecycle integrity gate, inspect a
deterministic read-only plan before choosing any repair:

```bash
pcl repair lifecycle --json
pcl repair lifecycle --dry-run --json
```

Bare and explicit `--dry-run` are equivalent. Both return
`lifecycle-repair-plan/v1` with `mode: "plan"`, `mutated: false`, a zero-filled
summary for `structural`, `semantic`, `human_review`, and `unsupported`, and
canonically sorted actions. The planner writes no database row, event, outbox
record, JSONL line, report, dashboard, copied Evidence, or other file. It never
executes a command from the plan.

Each action has a stable `action_kind`, concrete entity IDs, related IDs, and a
canonical sort key. Structural means only that all IDs already exist and the
relationship is unambiguous from stored data—for example, a healthy Evidence
ID already stored by a passing Test whose acceptance link is missing. Apply
only those recognized, safe structural actions with:

```bash
pcl repair lifecycle --apply-structural --json
```

The command rebuilds the current plan, rechecks every selected relationship
inside one transaction, and emits one audited batch event. It never executes
the plan's command strings. A stale precondition, unknown action kind, or
invalid relationship rolls the whole batch back.
There is no lifecycle repair `--apply` mode.

Story review or waiver, Test-to-Story selection, Evidence selection or
replacement, status changes, Verification, and closing or reopening entities
remain semantic or human decisions. An exactly-one Story candidate is not an
automatic relationship. Missing, drifted, cross-target, wrong-role, or
conflicting Evidence is reported and never normalized. Inspect the suggested
read-only commands, choose semantics explicitly, and use only the appropriate
existing lifecycle command after human review.

Use dedicated link repair when the operator has already made the semantic
choice and only the stored relationship is wrong:

```bash
pcl test link TC-0001 --story US-0001 --evidence-id E-0007 --summary "Reviewed repair"
pcl evidence link E-0007 --target test_case:TC-0001 --role acceptance --summary "Restore missing routing row"
```

`pcl test link` can repair the Test pointer and routing link together. `pcl
evidence link` only inserts a routing link and refuses a terminal Test whose
stored Evidence pointer differs. Exact reruns are no-ops; neither command
replays status transitions or deletes historical Evidence.

Text output contains the same ordered classes and concrete IDs as JSON. Use
JSON for automation, but do not infer behavior from `reason` prose; consume the
versioned `classification`, `action_kind`, `sort_key`, and entity fields.

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

### Audit integrity recovery

Start with the read-only check. It never flushes the projector:

```bash
pcl audit check --json
```

The report uses `audit-check/v1`, includes SQLite/JSONL hashes and counts, and
separates anomalies into `repairable`, `human_review`, and `unsupported`.
Exit 0 is clean, exit 6 means a supported or review-required issue, exit 7 means
an unsupported format, and exit 8 means the check itself failed.

For a pending or retryable outbox suffix, preview before applying:

```bash
pcl audit repair --dry-run --json
pcl audit repair --apply --json
```

Apply refuses review-required and unsupported anomalies. A successful apply
backs up the old JSONL, reports before/backup/after SHA-256 values, projects each
pending event once, and appends `audit_repair_applied` through the ordinary
event/outbox transaction.

For duplicate, mismatched, malformed, JSONL-only, or legacy lines, generate a
verified SQLite-derived preview and inspect the reported isolated lines:

```bash
pcl audit rebuild-jsonl --from-sqlite --output /tmp/events.rebuilt.jsonl --json
pcl audit rebuild-jsonl --from-sqlite --apply --json
```

Apply writes and verifies a same-directory temp file, preserves the complete old
file under `.project-loop/reports/audit-backups/`, atomically replaces JSONL,
reconciles its outbox delivery markers, and appends `audit_jsonl_rebuilt`.
Unknown data is preserved in the backup and reported; it is never imported into
SQLite or silently discarded. This command does not repair corrupt SQLite and
does not rebuild domain state from JSONL.

Evidence missing files, metadata/content mismatches, and orphan temporary files
are report-only in this version. Do not delete or fabricate them to make the
check clean; preserve them for human review.

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
