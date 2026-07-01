# Task 0058: Dogfood Usability Hardening

## Goal

Apply early downstream dogfooding feedback so Project Loop Harness remains useful
without making small changes feel ceremonial.

## Scope

- Make generated job prompts explicitly include the required `agent-output/v1`
  Markdown shape.
- Make `pcl next` easier to interpret by adding stable guidance fields for how
  humans and agents should treat the recommended command.
- Document `approved`, `needs_human`, `inconclusive`, and `rejected`
  verification result semantics.
- Encourage feature coverage jobs to emit ready-to-review `pcl feature add`,
  `pcl story draft`, and `pcl test plan` commands.
- Keep implementation/build/test/screenshot evidence tied through existing
  feature and test lifecycle commands rather than adding a schema migration.

## Acceptance Criteria

- `pcl prompt job` output mentions `agent-output/v1`, the H1 summary, and the
  required `## Findings` and `## Evidence` headings.
- Feature coverage prompts include ready-to-review command examples for feature,
  story, and test registration where appropriate.
- `pcl next --json` includes `run_policy` and `human_guidance` while preserving
  existing keys.
- `pcl next --explain` and dashboard HTML render the new guidance fields.
- Dashboard data contract docs and tests include the new guidance fields.
- No schema migration or external dependency is added.

## Do Not

- Do not auto-run feature registration from agent output yet.
- Do not make screenshots mandatory for every feature.
- Do not change the meaning of existing `pcl next` keys.
- Do not add hosted services or external notification hooks.
