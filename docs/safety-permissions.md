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

## MCP guidance

MCP should be an optional bridge to external services. It should not replace local CLI state mutation in the first implementation.

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
