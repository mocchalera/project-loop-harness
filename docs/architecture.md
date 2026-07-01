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
| CLI | Mutate state, validate, render, schedule | Become model-specific |
| SQLite | Store current normalized state | Be hand-edited by agents |
| JSONL | Preserve audit trail | Serve as query engine |
| HTML | Human-readable view | Become source of truth |
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
   ├─ dashboard/
   ├─ evidence/
   ├─ exports/
   ├─ reports/
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
