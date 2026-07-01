# Task 0005: Agent Integration Adapters

## Goal

Let the harness generate prompts and ingest outputs from coding agents without becoming locked to one vendor.

## Read first

- `docs/architecture.md`
- `docs/distribution.md`
- `skills/project-control-loop/SKILL.md`

## Scope

Implement adapter interface:

```text
AgentAdapter.generate_command(job) -> command or manual instructions
AgentAdapter.ingest_output(path) -> structured result
```

Initial adapters:

- `manual`: writes prompt files and tells the user what to run;
- `codex_exec`: shell command template for Codex non-interactive mode;
- `claude_manual`: prompt/export instructions for Claude Code.

## Acceptance criteria

- `pcl prompt job <job_id>` prints a complete prompt.
- `pcl agent command <job_id> --adapter codex_exec` prints a runnable command template.
- `pcl ingest-agent-run <path>` records output evidence.

## Do not

- Do not require API keys.
- Do not send data to external services automatically.
