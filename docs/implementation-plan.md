# Implementation Plan

## Milestone 0: Starter skeleton

Already present in this repository.

## Milestone 1: Reliable local state

- Harden `pcl init`.
- Add schema migrations.
- Add typed command errors.
- Add tests for init, validation, render, feature add, defect open, export.
- Make dashboard deterministic.

## Milestone 2: Workflow runner

- Load workflow YAML.
- Create workflow runs and agent jobs.
- Generate prompt files.
- Support manual agent execution first.
- Add ingest command for agent outputs.
- Add verifier result recording.
- Add explicit job/run/goal lifecycle commands so dogfooding loops can finish.
- Add explicit defect lifecycle commands tied to evidence and verification.
- Add strict validation invariants for evidence-backed terminal states.
- Add strict audit-log integrity checks between SQLite events and JSONL.
- Add validation diagnostics that route strict failures into next actions and reports.
- Add explicit escalation lifecycle commands for human-required stops and resumes.
- Add explicit decision lifecycle commands for durable human choices.
- Link escalations to decisions so human-required ambiguity and the recorded choice are traceable.
- Add guided `pcl next` metadata so agents and humans can distinguish blocking, human-required, and safe-to-run actions.
- Document the README golden path so new operators can run the current loop end to end.
- Document the recovery playbook for strict validation failures, audit mismatches, missing evidence, and stale generated artifacts.
- Refresh example project configs so operators can copy, initialize, validate, render, and follow `pcl next`.

## Milestone 3: Agent integrations

Complete as of Task 0026.

- Stabilized the agent adapter command contract for manual, Codex CLI, Claude Code, and generic shell handoffs.
- Validated agent output before ingesting it as durable evidence.
- Added Codex non-interactive command generation without automatic execution.
- Hardened the generated Codex CLI adapter command before adding any automatic execution.
- Added Claude Code prompt/export handoff.
- Hardened the Claude Code manual adapter instructions before adding any automatic execution.
- Added generic shell adapter command generation for vendor-neutral local command handoff.
- Completed agent job evidence ingestion visibility across job read/list, dashboard data, dashboard HTML, and reports.

## Milestone 4: Rich dashboard

- Version the dashboard data contract so dashboard HTML and future tooling render from a stable JSON review artifact.
- Link jobs, evidence, reports, and verifications through deterministic dashboard navigation fields and HTML anchors.
- Surface validation, human queues, defects, failed runs, and failed jobs through a deterministic risk/blocker summary.
- Current goal panel.
- Active workflow panel.
- Agent jobs panel.
- Verification panel.
- Escalation panel.
- Budget panel.
- Evidence links.
- Evidence-backed Markdown reports for goals, workflow runs, and defects.

## Milestone 5: Distribution

Complete as of Task 0030.

- Codex plugin package with skill, hooks metadata, marketplace example, and MCP example.
- GitHub marketplace file example that documents the runtime boundary.
- Optional local stdio MCP server with read-only default and explicit local-render approval.
- Reusable GitHub Action for validation and dashboard rendering.
- Wheel-install smoke test covering `pcl`, `pcl-mcp`, bundled templates, validation, render, and next-action routing.
- Operator adoption guide covering private Git install, local wheel handoff, new-project initialization, commit boundaries, and first agent prompts.

## Milestone 6: Dynamic workflows, carefully

Only after static workflows are stable:

- workflow proposal mode as non-executable review artifacts;
- human approval and cancellation of workflow proposals;
- workflow verifier for proposed and approved workflow YAML;
- limited execution sandbox for explicit local dry-run and allowlisted execution.

## Milestone 7: Automatic execution, guarded

- Add an explicit workflow executor that drives approved templates through
  run creation, command sandbox execution, agent adapter execution, evidence,
  automated verification, run completion, and render.
- Add a bundled executor smoke workflow so initialized projects can dogfood the
  guarded executor immediately.
- Add explicit executor retry and resume paths so failed or interrupted
  automatic runs remain recoverable through the state machine.
- Add guarded story and test case lifecycle commands so feature coverage
  artifacts live in durable state instead of free-form agent output only.
- Accept simple workflow rule expressions as plain YAML scalars so initialized
  templates remain runnable across small template formatting changes.
- Add strict validation invariants for evidence-backed terminal test case states.
- Add read-only feature inspection commands so story, test, defect, and report
  workflows can find feature IDs and statuses directly through the CLI.
- Include linked features, user stories, test cases, and terminal test evidence
  in goal and workflow-run reports.
- Add feature-level evidence reports for reviewing one feature's stories,
  tests, defects, related workflow runs, evidence, and events.
- Expand CSV export into a complete deterministic review artifact for loop
  state, evidence, verifications, human queues, events, and workflow proposals.
- Add run/status filters for `pcl jobs list` so dogfooding agents can inspect
  active job queues without dumping all historical jobs.
- Add evidence-backed `pcl feature status` transitions so implemented or waived
  features can be reconciled without direct database edits.
- Route `pcl next` toward concrete uncovered features before falling back to a
  generic feature coverage goal.
- Add read-only `pcl migrate status` so schema migration state can be inspected
  before applying pending migrations.
- Include both dashboard HTML and dashboard data artifact paths in
  `pcl render --json`.
- Add a machine-readable Codex plugin package inventory and tests that keep the
  bundled plugin file set deterministic.
- Return both generated dashboard artifact paths from the gated MCP
  `render_dashboard` tool.
- Cancel active jobs when a workflow run fails so terminal runs do not leave
  stale queued work behind.
- Include output and ingest metadata in `pcl prompt job --json` so agent
  handoff automation can use one prompt response without path reconstruction.
- Expose derived escalation/decision link IDs on human queue CLI read/list
  commands.
- Filter workflow proposal review lists by derived status so dogfooding agents
  can inspect proposed, approved, or cancelled proposal queues directly.
- Treat sandbox execute runs with zero runnable commands as non-successful
  no-ops instead of reporting a misleading successful execution.
- Reject guarded executor runs with no executable command or agent steps before
  creating a workflow run.

## Milestone 8: Dogfood usability hardening

- Make generated job prompts repeat the required `agent-output/v1` Markdown
  shape directly in the prompt body.
- Clarify `safe_to_run`, `requires_human`, and verification result semantics for
  operators and agents.
- Encourage feature coverage outputs to include ready-to-review `pcl feature`,
  `pcl story`, and `pcl test` commands before adding heavier automation.
- Keep build, test, screenshot, and UX verification evidence attached through
  existing evidence-backed feature and test lifecycle commands.
- Add checkpoint review commands and `pcl next` routing so every several done
  features triggers a human commit/package, UX checklist, and next-priority
  review before continuing feature coverage.
- Add PyPI/TestPyPI Trusted Publishing workflow and docs so public package
  releases can use GitHub OIDC instead of long-lived PyPI tokens.
