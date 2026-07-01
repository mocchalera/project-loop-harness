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

## MCP guidance

MCP should be an optional bridge to external services. It should not replace local CLI state mutation in the first implementation.

## Workflow sandbox guidance

`pcl workflow sandbox` is local and explicit. Dry-run mode is the default.
Execution requires `--execute`, applies only to approved workflow templates, and
uses `subprocess.run(..., shell=False)` for allowlisted commands. Proposals and
standalone files remain review artifacts and are not executable.

## Automatic executor guidance

`pcl loop execute` is an explicit local automation boundary. It refuses blocked
commands before creating a run, executes command steps only through the sandbox,
and requires `--allow-agent-exec` before launching any agent adapter command.
Generated execution evidence and events remain the source for review.
