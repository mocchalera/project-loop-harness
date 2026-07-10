# Architecture

## Definition

Project Loop Harness is a local agentic project control plane.

It is designed to let coding agents work through bounded loops while humans can inspect progress through a deterministic dashboard.

## System layers

```text
1. Human goal
2. pcl CLI / harness runtime
3. Workflow templates
4. Agent jobs and optional subagents
5. Evidence collection
6. Verification
7. SQLite state and JSONL audit log
8. HTML dashboard and markdown reports
9. Stop / retry / escalation decisions
```

## Key separation

| Layer | Responsibility | Must not do |
|---|---|---|
| Skill | Teach agent how to use the harness | Mutate state directly |
| CLI | Mutate state, validate, render, schedule, and package read-only context | Become model-specific |
| SQLite | Store current normalized state | Be hand-edited by agents |
| JSONL | Preserve audit trail | Serve as query engine |
| HTML | Human-readable view | Become source of truth or agent context |
| Plugin | Package Codex-facing assets | Replace CLI/runtime |
| MCP | External tool bridge | Own local state logic |

## Local project installation shape

```text
target-project/
├─ AGENTS.md
├─ CLAUDE.md
├─ pcl.yaml
├─ .agents/
│  └─ skills/
│     └─ project-control-loop/
│        └─ SKILL.md
└─ .project-loop/
   ├─ project.db
   ├─ events.jsonl
   ├─ goals/
   ├─ workflows/
   ├─ workflow-proposals/
   ├─ dashboard/
   ├─ evidence/
   ├─ exports/
   ├─ reports/
   ├─ tmp/
   ├─ cache/
   └─ worktrees/
```

## Control flow

```text
pcl loop run defect_repair --defect D-0001
  -> creates workflow_run
  -> creates agent_jobs
  -> generates prompts
  -> invokes configured agent runner or asks human to run the prompt
  -> ingests outputs and evidence
  -> runs verifier
  -> updates state through service layer
  -> validates
  -> renders dashboard
  -> stops, retries, or escalates
```

## Why SQLite + JSONL

SQLite is used for current normalized state and dashboard queries.
JSONL is used for append-only audit and reconstruction.

Do not choose only one:

- SQLite alone is hard to review in Git.
- JSONL alone is awkward for query, joins, and validation.
- CSV alone is too easy to corrupt as the loop grows.

## Why CLI first

Agent Skills are instructions. They cannot reliably guarantee migrations, validation, deterministic rendering, or guarded state transitions by themselves.

The CLI is the runtime body. The Skill only tells agents how to use it.

## Guarded executor boundary

`pcl workflow guard` and `pcl loop execute` use an allowlisted host-subprocess
executor. The executor passes an argv list with `shell=False`, fixes the working
directory to the project root, and inherits only an explicit environment-variable
allowlist. It does not provide OS, network, or filesystem isolation. A future
container backend may implement stronger isolation behind an explicit backend
contract; the current host backend must never be presented as a sandbox.

Each stdout and stderr stream is drained incrementally and retains at most 1 MiB
by default. Evidence records the configured cap, original byte count, retained
byte count, head-retention strategy, timeout/termination status, and truncation
reason. Secret-shaped output is conservatively redacted before artifact storage;
raw output is not retained elsewhere. Redaction metadata is reviewable, but the
filter is not a secret scanner and does not prove that output is secret-free.

## Machine Context Packs

`pcl context pack` is a read-only packaging surface for focused agent handoffs.
It must not mutate SQLite, append events, write packs to disk, or parse
generated dashboard HTML.

Job packs and task packs share the additive `context-pack/v1` JSON contract.
Job packs include lease fields and rubric-aware verification columns. Task
packs include task dependencies, dependents, linked goal/feature/defect
context, sibling tasks, and recent events.

Role profiles affect which sections fit under a tight budget, but included
sections are always rendered in canonical document order. Budget selection uses
the deterministic `charclass/v1` estimator rather than parsing model-specific
tokenizers or slicing generated Markdown after rendering.

## Explainable Code Context

`pcl index build` creates an explicit local snapshot of code files with
gitignore-aware omissions, hashes for small text files, symbol-lite summaries,
and test hints. The index lives in schema version 4 tables and appends an event
for each build.

The index is not source of truth. The working tree and Git state remain
authoritative; `pcl index status` and `pcl impact` surface staleness warnings
when the snapshot differs.

`pcl impact --diff` writes a `context-receipt/v0` JSON artifact as normal
evidence. The receipt records `included_candidate_context`, `omitted`, and
`staleness_warnings` so later review can see what PLH provided and why.
