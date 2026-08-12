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

The filesystem current-proof linearization point is the successful final
retained-descriptor reseal, called **V**. Acceptance is logically linearized at
V only if the already-staged SQLite transaction subsequently commits. The
retained manifest/member/root identity is therefore a statement about bytes at
V, not a claim that a pathname remains unchanged through the later physical
SQLite commit. Commit failure or an unknown commit outcome retains the existing
fail-closed outcome contract. Drift detected before V remains an effect-zero
pre-commit failure.

On Linux, SQLite resolves the descriptor-root proxy back to the requested
pathname before journal management. Task Accept therefore rechecks that
requested-root identity in the physical pre-commit guard. A rename or
replacement in that interval is a typed, fully rolled-back
`task_accept_root_changed`; neither the displaced project nor its replacement
is accepted. Strict Evidence resolution and final resealing still open every
artifact component relative to the retained descriptor, so this availability
qualification does not relax symlink, hardlink, regular-file, containment, or
byte-identity checks.

## Copied Evidence and durable retry authority

The artifact is opened component by component without following symlinks,
must be a regular single-link project-relative file, and is re-read inside the
exclusive project lock and before the terminal gate. Its durable copy uses a
content-addressed filename and exclusive no-overwrite publication. The durable
authority is a set of canonical `PCLF1` framed, no-overwrite records under
`.project-loop/task-accept-recovery/v1`. It contains the full request binding,
ID reservation index and manifest, Test/Feature/Task proof bindings, structural
plan, SQLite/projection/render authorities, a generation manifest, and one
continuous reserved-to-sealed ledger head. The canonical two-Test fresh form
has 31 records; exact replay verifies every record and publishes none.

The acceptance receipt binds the Evidence row and direct-link hashes, manifest
and member hashes, Evidence recording event and complete pre-terminal event
suffix, acceptance HWM, and full request input digest. An exact retry
recomputes that identity and revalidates the DB authority, immutable ledger,
copied member, current direct link sets, full strict result, and P0-B current
proof. Only then does it return `mode=exact_replay_success`, `status=no_op`;
it appends no rows,
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
Immediately before publishing any accepted marker, that recovery reruns strict
formal validation and P0-B terminal readiness against the current snapshot. A
new blocker returns `mode=accepted_authority_tail_recovery_error`, publishes no
marker, and performs no business DML. A healthy recovery publishes the fixed
six-record tail and returns `status=recovered`; it does not rerun Test, Feature,
Task, Evidence, event, or outbox business DML. A subsequent exact request is a
zero-effect replay.

Retained proof descriptors remain open through the physical SQLite commit. The
first post-commit callback rechecks them before accepted authority, projection,
render, or the sealed tail is published. If it observes a non-cooperative
filesystem change after V, the business transaction remains committed but the
command returns exit `6`, `task_accept_post_acceptance_corruption`, phase
`post_acceptance_corruption`. It publishes neither a healthy accepted marker
nor projection/render/sealed-tail authority; the normal two-Test case retains
the deterministic 24-record pending authority. A second live proof check after
projection isolates corruption that lands after the immediate callback and
before rendering, retaining the 25-record accepted pre-tail authority. Because
rendering has not started and corrupt proof cannot be rendered or recovered as
healthy, that envelope reports `receipts.render_status=not_started` together
with `pending_tail.render_pending=false`.

Changes after either immediate check are still post-acceptance corruption; they
do not retroactively roll back terminal SQLite state. The next validation,
terminal-readiness consumer, exact replay, or tail recovery re-reads the
manifest and copied member and blocks on missing, replaced, or hash-mismatched
current Evidence. `pcl validate` and `pcl doctor` report current copied
acceptance corruption as an error. Recovery never overwrites or adopts those
bytes and cannot publish a healthy marker until legitimate new immutable
Evidence and supersession/current-proof state exist.

When SQLite committed but projection or rendering did not finish, the JSON
envelope has `mutation_committed: true`, `safe_to_retry_original: false`, and
an explicit `safe_retry_action`. Use the reported `pcl audit flush --json`
dedicated recovery action; do not re-run the original business mutation as a
recovery action. An unknown commit outcome is never reported as
success or as a safe original retry; audit inspection and the same dedicated
tail recovery determine whether a committed authority exists.

Every JSON result uses `schema_version=task-accept-envelope/v1`, exactly 26
top-level fields and 25 non-negative effect counters. Serialization first
passes both the versioned JSON Schema shape and semantic accounting checks.
`mutation_committed` is always boolean, including commit-acknowledgement loss.
Fresh success is `fresh_success/success`; replay is
`exact_replay_success/no_op`; known postcommit tail failures and dedicated
recovery have their own fixed modes. Human output is one canonical line on
stdout, with errors using the corresponding fixed `ERROR task_accept` line.

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
