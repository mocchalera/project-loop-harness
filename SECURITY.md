# Security Policy

Project Loop Harness is a local-first CLI/runtime. It stores project-loop state
in the target repository's local `.project-loop/` directory.

## Supported Versions

The current public release line is `0.1.x`.

## Reporting A Vulnerability

Please open a GitHub security advisory or a private issue with enough detail to
reproduce the problem. Do not include real secrets, production credentials, or
private project data in public issues.

## Security Boundaries

- Agents must not edit `.project-loop/project.db` directly.
- Agents must not edit `.project-loop/events.jsonl` directly.
- Generated dashboard HTML is a view, not source of truth.
- Workflow execution is local and guarded; agent execution requires explicit
  opt-in.
- The optional MCP server defaults to read-only behavior and redacts
  secret-shaped values.

If you are using Project Loop Harness in a sensitive repository, keep local
state, evidence, and generated reports out of public commits unless your team
has reviewed them.
