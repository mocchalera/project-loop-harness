# Dogfood Feedback: ax1-moc1 (external project, agent operator)

Source: cockpit task `ae7cd335` (codex / gpt-5.5 xhigh, YOLO mode),
project `~/Dev/ax1-moc1`, 2026-07-06. The agent implemented a
responsive LP from 10 reference comps end-to-end under PLH
(`project-control-loop` skill + pcl 0.2.x), completed in ~21 minutes
with TC-0001..3 passing, F-0001 passing, US-0001 approved, J-0001..3
passed, `pcl validate --strict` green, and stopped correctly at the
human verification gate. Feedback below was then given by the agent
on request. This is the first recorded end-to-end PLH run by a
non-PLH-developer operator on a non-PLH project.

## What worked (agent's words, condensed)

- `pcl next` was excellent: it surfaced the next job, the pending
  human verification, and `requires_human: true`, which prevented
  the agent from self-approving.
- `pcl test pass --evidence` drew the "implementation is done" line
  well; binding rendered screenshots + visual-check JSON as evidence
  fits web/design work.
- Keeping dashboard HTML out of machine state was validated in
  practice — CLI/JSON/reports sufficed.
- The validate/render ritual felt like healthy hygiene, not busywork.

## Friction points (verbatim intent, each mapped to a candidate task)

| # | Feedback | Candidate response | Size |
|---|---|---|---|
| F1 | `pcl feature status F-0001 --status passing` exits 2 on "already passing" — hostile to agents; idempotent transitions should exit 0 + `changed: false` | Idempotent same-state lifecycle transitions across feature/test/story/task/goal commands (no state-change event on no-op) | S |
| F2 | `--evidence` is a single string; multiple artifacts had to be `;`-joined | Repeatable `--evidence` (and/or JSON array) on evidence-accepting commands | S |
| F3 | `jobs list --json` shows empty evidence despite `output_path`; wanted `pcl jobs complete --evidence` | Evidence linkage for job completion | S–M |
| F4 | `feature_coverage` still queues mapper/story_writer/test_designer jobs when stories/tests already exist; agent had to write "already satisfied" reports to close them | Existing-coverage detection → mark such jobs satisfied/no-op | M |
| F5 | At the human gate, `pcl next` should also say "agent stops HERE" and provide ready-to-send approval-request text for the user | Human-gate handoff text in `pcl next` (Japanese-first; Milestone 13 adjacency) | M |
| F6 | Wants an evidence bundle type for screenshot + viewport + visual-check report | Evidence bundle design (fold into F2/F3 design) | M |
| F7 | **Top ask**: a `pcl finish`-style closeout command — check test/job/story states, validate, render, generate the run report, and summarize remaining human gates in one step; "closing out PCL correctly" carried more cognitive load than the implementation itself | Closeout/finish command design (builds on checkpoint 0059 concepts) | M–L |

## Cross-links to open design questions

- F2/F3/F6 intersect the open `--output-file` question (ad-hoc
  executed-feedback evidence path from the v0.2.0 plan's M2 dogfood
  findings): all four are the same underlying gap — evidence entry
  ergonomics for operators outside the job loop. They should be
  designed together, not piecemeal.
- F5 feeds the Judgment pillar (Milestone 13 human decision UI) and
  the standing wish that escalations reach humans in readable
  Japanese.
- F1 is a pure agent-ergonomics fix with no contract risk and is the
  cheapest credibility win.

## Explicitly NOT conceded

The agent suggested nothing that weakens the epistemic boundaries:
the human verification gate itself was praised, not contested. No
item above requires auto-approval, auto-execution, or go/no-go
verdicts, and none touches the semantic promotion gate.
