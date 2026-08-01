# Safety and Permissions

## Principle

The harness should be useful locally before it is powerful externally.

## Never automate without explicit approval

- production database queries;
- destructive file operations;
- secret access;
- deployment;
- billing changes;
- authentication changes;
- database migrations;
- dependency additions;
- Slack or email messages to humans;
- GitHub PR creation or merge.

## Permission model

`pcl.yaml` defines:

- directories agents may modify;
- directories agents may not modify;
- actions requiring human approval;
- max loop iterations;
- max fix attempts.

PCL guidance does not grant authority. The user's request, repository policy,
and host approval boundary remain authoritative. `pcl guide` classifies each
step with one of these operator-facing authority classes:

| Class | Meaning | Default boundary |
| --- | --- | --- |
| `read_only` | Inspect machine state without writing project or PCL artifacts | Agent-safe within the selected project and target |
| `pcl_local_state` | Mutate only project-local PCL state or Evidence through a PCL command | Agent-safe only when the user authorized the tracked workflow |
| `repository_write` | Create or update source, configuration, or generated review artifacts | Requires repository/file-write authority from the user or task |
| `external_write` | Change an external or production system | Always requires explicit human authority; the local guide does not propose it |
| `terminal_transition` | Mark a Story, Test, Feature, Task, or Goal terminal | Requires satisfied lifecycle gates; some transitions also require an explicit human semantic decision |

`mutates_state=false` in `command-guide/v1` means that the command does not
mutate authoritative PCL domain state. It is not a general side-effect claim.
For example, `pcl render` writes deterministic dashboard artifacts and is
therefore `repository_write`; `pcl init` writes both project files and local PCL
state.

Human approval and host execution authority are separate. A Story approval
receipt records a semantic decision; it does not grant authority for an
external or production write. Conversely, repository-write authority does not
let an agent approve a Story or waive terminal Evidence. When a command's
prerequisites are missing, follow its read-only `failure_recovery` route instead
of guessing, retrying a terminal mutation, or selecting another target.

Task `done` has no force, override, lite-mode, configuration, or environment
bypass. A linked Task requires its Feature to be explicitly `done` with healthy
acceptance Evidence; `ready_to_close` is advisory projection only. Standalone
Tasks do not acquire a new Evidence requirement. Both direct Task completion
and Task-bound finish use the current `terminal-readiness/v1` proof snapshot.
Their typed pre-commit failures preserve Task, event, outbox, audit JSONL, and
dashboard bytes.

`pcl task accept` is a fixed `pcl_local_state` plus local Evidence-copy
operation. It does not add a force, override, lite, configuration bypass,
human approval receipt, or implicit Story approval. It is allowed only for an
already in-progress Task whose projected final Feature, Tests, current copied
Evidence, global guards, and P0-B proof all pass. Exact retries are read-only
verification. A post-commit exit 6 must be recovered through the reported
projection or render command, not by replaying the business request.
Projection recovery may publish only the receipt-bound Task Accept tail record
and acceptance marker after independently revalidating committed DB authority.
The final retained-descriptor reseal is the filesystem proof linearization
point. A non-cooperative change after that point is post-acceptance corruption,
not a pre-commit rollback condition. The immediate post-commit check runs
before healthy accepted authority, projection, render, or tail publication;
detected corruption returns exit 6 and remains blocked in validation and tail
recovery. This classification is not an advisory-lock guarantee and does not
claim pathname currentness through the physical SQLite commit.

## MCP guidance

MCP remains an optional local bridge. Its default mode is `read-only`.
`local-render` adds only deterministic dashboard rendering. The single narrow
mutation mode `task-accept-write` must be selected in process argv and exposes
only Atomic Task Accept in addition to the read tools. Initialize fields and
request-time aliases cannot elevate authority; unauthorized listing and
dispatch are both denied before arguments, root, artifacts, DB, or locks are
examined.

## Guarded executor guidance

`pcl workflow guard` is local and explicit. Dry-run mode is the default.
Execution requires `--execute`, applies only to approved workflow templates, and
uses an argv list with `shell=False` for allowlisted commands. Proposals and
standalone files remain review artifacts and are not executable. The host process
has no OS, network, or filesystem isolation. Parent environment inheritance is
allowlisted, and output is capped and redacted before Evidence storage.

`pcl workflow sandbox` remains a deprecated compatibility alias through the
`0.3.x` release line. It emits a warning on stderr and does not imply isolation.

## Automatic executor guidance

`pcl loop execute` is an explicit local automation boundary. It refuses blocked
commands before creating a run, executes command steps only through the guarded executor,
and requires `--allow-agent-exec` before launching any agent adapter command.
Generated execution evidence and events remain the source for review.
