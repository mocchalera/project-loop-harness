# Task 0065: Dashboard Human Decisions And Locale

## Goal

Make the generated dashboard surface every current human decision point in one
prominent place, and add English/Japanese HTML chrome localization without
changing the machine-readable dashboard data contract values.

## Scope

- Add an additive `human_decisions` section to `dashboard-data.json`.
- Include open decisions, open escalations, active `needs_human`
  verifications, and the current `pcl next` action when it requires a human.
- Keep `dashboard-data.json` keys and values English and locale-independent.
- Render a "Needs Your Decision" HTML section immediately after validation
  context and before the other dashboard panels.
- Add `pcl render --locale ja`, with flag precedence over `dashboard.locale`
  in `pcl.yaml`, then default `en`.
- Localize dashboard HTML chrome only; never translate stored user content,
  entity ids, commands, or JSON values.
- Update tests, README, and dashboard data contract documentation.

## Acceptance Criteria

- `dashboard-data.json` contains `human_decisions.count` and
  `human_decisions.items`.
- Open decisions include id, question, recommendation, created time, linked
  escalation ids, and a concrete `pcl decision resolve ...` command.
- Open escalations include id, severity, question, recommendation, created
  time, linked decision ids, and a `pcl escalation resolve ...` command.
- Active-run `needs_human` verifications include id, workflow run id, reasons,
  created time, and a `pcl escalation open --run ...` command.
- Inactive workflow runs do not contribute verification decision items.
- The current `pcl next` action appears only when `requires_human` is true.
- Human decision items sort by severity rank, created time, then id.
- Default English rendering keeps existing dashboard assertions valid.
- Japanese rendering sets `lang="ja"` and is deterministic across repeated
  renders.
- Invalid locales fail with a clear list of supported locales.
- `ruff check .` passes.
- Full `pytest` passes.
- The `/tmp/pcl-demo-hd` smoke flow proves human decision count and Japanese
  rendering.

## Do Not

- Do not add a schema migration.
- Do not add dependencies.
- Do not add JavaScript.
- Do not mutate project-loop state as part of rendering.
- Do not append events during rendering.
- Do not localize `dashboard-data.json` keys or values.
- Do not make agents read or edit generated dashboard HTML as state.
