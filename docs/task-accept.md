# Atomic Task Accept

`pcl task accept` is the fixed local surface for accepting one complete,
in-progress Task without exposing a sequence of partially committed lifecycle
commands.

```bash
pcl task accept T-0001 \
  --artifact artifacts/acceptance.txt \
  --command "pytest -q" \
  --summary "Acceptance suite passed" \
  --copy \
  --test TC-0001 \
  --test TC-0002 \
  --json
```

`--copy` and at least one `--test` are mandatory. The selected Tests must be
the exact set of non-waived Tests for the Task-linked Feature. Every selected
Test must be non-passing and linked to an approved or explicitly waived Story.
This command does not approve or waive Stories and does not create an Evidence
Set.

## Atomic state contract

One schema-8 `BEGIN IMMEDIATE` transaction creates exactly one
`adhoc_artifact` Evidence row, links it directly to each selected Test and the
Feature as `acceptance` and to the Task as `supporting`, passes the Tests,
projects and records Feature `passing` when required, marks the Feature `done`,
runs full strict validation exactly once, applies the strict-free P0-B terminal
readiness classifier, and finally changes the Task from `in_progress` to
`done`. Every staged event has exactly one outbox row.

The final Task row, `task_status_changed` event, and its outbox row are the only
three DML statements after the strict/P0-B gate. A pre-commit failure rolls all
business, event, and outbox rows back.

## Copied Evidence and durable retry authority

The artifact is opened component by component without following symlinks,
must be a regular single-link project-relative file, and is re-read inside the
exclusive project lock and before the terminal gate. Its durable copy uses a
content-addressed filename and exclusive no-overwrite publication. Claim,
Evidence reservation, and generation records are immutable project-local
files under `.project-loop/evidence/task-accept-*`.

The acceptance receipt binds the Evidence row and direct-link hashes, manifest
and member hashes, Evidence recording event and complete pre-terminal event
suffix, acceptance HWM, and full request input digest. An exact retry
recomputes that identity and revalidates the DB authority, immutable ledger,
copied member, current direct link sets, full strict result, and P0-B current
proof. Only then does it return `already_accepted`; it appends no rows,
publishes no files or markers, projects no JSONL, and renders no dashboard.
The same Task with a different request conflicts. Source hash drift,
superseded or replaced proof, ledger gaps/forks, copy or manifest tampering,
and ambiguous or missing authority fail closed.

A stale pre-commit attempt may append a successor business generation only
when the old immutable request is readable and the accepted DB authority is
absent. Accepted replay never advances the business generation.

## Commit and tail outcomes

Exit codes are:

- `0`: accepted or verified exact replay;
- `1`: lifecycle, current-proof, conflict, or strict-readiness rejection;
- `2`: invalid fixed input or unsafe artifact input;
- `3`: project not initialized;
- `4`: durable state, ledger, copy, or internal integrity failure;
- `6`: commit/projection/render outcome needs recovery.

When SQLite committed but projection did not finish, `pcl audit flush --json`
projects the committed outbox and runs the dedicated Task Accept tail recovery.
That recovery validates current DB/proof authority, appends an immutable
tail-recovery generation, and publishes the missing acceptance marker; it does
not run Test, Feature, Task, Evidence, event, or outbox DML. A subsequent exact
request is a zero-effect accepted replay. Rendering recovers separately through
`pcl render --json`.

When SQLite committed but projection or rendering did not finish, the JSON
envelope has `mutation_committed: true`, `safe_to_retry_original: false`, and
an explicit `safe_retry_action`. Use `pcl audit flush --json` for projection
or `pcl render --json` for rendering; do not re-run the original business
mutation as a recovery action. An unknown commit outcome is never reported as
success or as a safe original retry; audit inspection and the same dedicated
tail recovery determine whether a committed authority exists.

## MCP capability

The only MCP write opt-in is process startup:

```bash
pcl-mcp --stdio --root /absolute/project --approval-mode task-accept-write
```

That mode exposes the four read tools plus `task_accept`, and does not expose
`render_dashboard`. Default `read-only` and `local-render` modes deny both
listing and dispatch. Initialize parameters, client capabilities, request
headers, queries, aliases, or tool arguments cannot promote the startup mode.
CLI JSON and MCP tool text use the same canonical envelope bytes, excluding
the CLI terminal newline.
