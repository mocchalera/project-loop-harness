# Agent Adapter Contract

Project Loop Harness does not execute external agents automatically. It creates a durable job, writes a prompt, emits an adapter command contract, and later ingests the output file as evidence.

## Flow

```bash
pcl jobs read J-0001
pcl prompt job J-0001
pcl agent command J-0001 --adapter manual --json
pcl agent command J-0001 --adapter codex_exec --json
pcl agent command J-0001 --adapter claude_manual --json
pcl agent command J-0001 --adapter generic_shell --json
pcl ingest-agent-run .project-loop/evidence/agent-runs/J-0001/output.md
```

The only state mutation in the external-agent return path is `pcl ingest-agent-run`.

`pcl prompt job J-0001 --json` is the compact handoff surface for automation.
It returns the prompt body plus the deterministic return path metadata. The
prompt itself repeats the required `agent-output/v1` shape so an agent can
produce ingestible evidence without first reading this contract:

```json
{
  "ok": true,
  "job_id": "J-0001",
  "workflow_run_id": "WR-0001",
  "workflow_id": "feature_coverage",
  "role": "mapper",
  "status": "queued",
  "prompt_path": ".project-loop/evidence/agent-runs/J-0001/prompt.md",
  "output_path": ".project-loop/evidence/agent-runs/J-0001/output.md",
  "ingest_command": "pcl ingest-agent-run .project-loop/evidence/agent-runs/J-0001/output.md",
  "expected_output_format": "Markdown report matching agent-output/v1...",
  "prompt": "# Agent Job J-0001\n..."
}
```

The non-JSON form stays optimized for humans and prints only the prompt text.
The prompt includes the required H1 summary plus `## Findings` and
`## Evidence` headings, and may include workflow-specific handoff guidance such
as ready-to-review `pcl feature add`, `pcl story draft`, or `pcl test plan`
commands.

## Adapter Command JSON

`pcl agent command J-0001 --adapter manual --json` returns:

```json
{
  "ok": true,
  "agent_command": {
    "contract_version": "agent-adapter-command/v1",
    "adapter": "manual",
    "job_id": "J-0001",
    "prompt_path": ".project-loop/evidence/agent-runs/J-0001/prompt.md",
    "output_path": ".project-loop/evidence/agent-runs/J-0001/output.md",
    "ingest_command": "pcl ingest-agent-run .project-loop/evidence/agent-runs/J-0001/output.md",
    "expected_output_format": "Markdown report matching agent-output/v1. First non-empty line must be an H1 summary; include required headings: ## Findings and ## Evidence. Recommended pcl commands are optional.",
    "instructions": "Read the prompt, write the result, then ingest it.",
    "command": null
  }
}
```

All adapters expose the same keys. `command` is nullable because manual adapters describe work instead of executing it.

## Paths

The expected output path is deterministic:

```text
.project-loop/evidence/agent-runs/<job_id>/output.md
```

`pcl ingest-agent-run` infers `<job_id>` from that path, validates the file against `agent-output/v1`, creates an `agent_output` evidence record, marks the job passed, appends `agent_output_ingested`, and records the output path on the job.

The ingest path must be the project-scoped `.project-loop/evidence/agent-runs/<job_id>/output.md`. Files from another directory, even if they contain an `agent-runs/<job_id>` segment, are rejected. Ingest is also a guarded state transition: cancelled or failed jobs cannot be revived by late output, and inactive workflow runs cannot accept new agent output.

If a job artifact has already been recorded with `pcl evidence add`, complete
the job with `pcl jobs complete <job-id> --evidence E-00xx` to link that
existing evidence row. Otherwise, keep using `pcl ingest-agent-run` for raw
agent output so PLH validates `agent-output/v1`, creates the evidence row, and
marks the job passed in one guarded transition.

After ingest, `pcl jobs read J-0001 --json` and `pcl jobs list --json` expose the derived evidence linkage:

```json
{
  "evidence_ids": ["E-0001"],
  "latest_evidence_id": "E-0001",
  "latest_evidence_path": ".project-loop/evidence/agent-runs/J-0001/output.md"
}
```

The linkage is derived from `agent_output_ingested` events, evidence-bearing `agent_job_completed` events, and `evidence` rows, not from a mutable `agent_jobs.evidence_id` column. Repeated ingests can therefore preserve multiple evidence ids while the latest evidence remains easy to find from job surfaces and the dashboard.

## Minimal Output File

See [agent-output-template.md](agent-output-template.md).

The first non-empty line must be a Markdown H1 and becomes the evidence summary. The file must include `## Findings` and `## Evidence`.

## Adapter Responsibilities

- Read the prompt from `prompt_path`.
- Write a Markdown result to `output_path`.
- Preserve evidence paths for claims.
- Recommend `pcl` commands instead of mutating state directly.
- Run `ingest_command` only after the output file exists.

## Codex Exec Adapter

`codex_exec` emits a copy-pasteable shell wrapper. It does not execute Codex from inside `pcl`.

The generated command:

- runs under `bash -lc`;
- enables `set -euo pipefail`;
- creates the output directory;
- calls `codex exec --cd <project-root> --output-last-message <output-path> - < <prompt-path>`;
- runs `pcl ingest-agent-run <output-path> --root <project-root>` only after Codex succeeds.

If Codex exits non-zero, no ingest is attempted. If Codex writes output that fails `agent-output/v1`, ingest exits with a typed validation error and the job remains unpassed.

## Claude Manual Adapter

`claude_manual` emits operator instructions. It does not execute Claude Code from inside `pcl`.

The instructions are labeled `Claude Code manual handoff` so operators can distinguish them from executable adapter commands.

The generated instructions tell the operator to:

- open or reference the prompt at `prompt_path` in Claude Code;
- ask Claude Code to return an `agent-output/v1` Markdown report;
- save the final response to `.project-loop/evidence/agent-runs/<job_id>/output.md`;
- run `pcl ingest-agent-run <output-path>` from the project root.

The returned file must include an H1 summary, `## Findings`, and `## Evidence`. If the file fails validation, ingest exits with a typed error and the job remains unpassed.

## Generic Shell Adapter

`generic_shell` emits a vendor-neutral shell wrapper. It does not execute the wrapper from inside `pcl`.

The operator sets `PCL_AGENT_COMMAND` to a local shell command that reads the prompt from stdin and writes an `agent-output/v1` Markdown report to stdout.

The generated command:

- runs under `bash -lc`;
- enables `set -euo pipefail`;
- creates the output directory;
- fails fast if `PCL_AGENT_COMMAND` is unset;
- calls `sh -c "$PCL_AGENT_COMMAND" < <prompt-path> > <output-path>`;
- checks that `<output-path>` is non-empty;
- runs `pcl ingest-agent-run <output-path> --root <project-root>` only after the shell command succeeds.

Example shape:

```bash
PCL_AGENT_COMMAND='my-local-agent --format markdown' bash -lc '...'
```

The local command must return the same output shape as every other adapter: first non-empty line is an H1 summary, with `## Findings` and `## Evidence` headings. If the command exits non-zero, no ingest is attempted. If the output fails `agent-output/v1`, ingest exits with a typed validation error and the job remains unpassed.

## Non-Goals

- No automatic external execution.
- No API key management.
- No direct SQLite writes by adapters.
- No generated dashboard edits.
