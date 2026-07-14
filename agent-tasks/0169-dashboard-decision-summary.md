# 0169: Dashboard decision summary

- **Status:** Complete
- **Milestone:** v0.5.0 Adoption / Distribution
- **Priority:** P0
- **Size:** S
- **Dependencies:** 0164
- **DB schema:** no change
- **Human approval:** user reported the missing decision content during dashboard dogfooding on 2026-07-14

## User problem

The dashboard's top-level `あなたの判断` card says that one decision is
needed, but it only shows the count. The actual reason and available choices
are hidden inside the collapsed advanced Project Loop details. An operator
cannot tell what they are being asked to decide from the default dashboard
view.

## Product outcome

When a human decision is pending, the top-level operator summary shows a
concise, localized preview of what needs deciding and the available choice
labels. Exact commands and the full audit detail remain in the advanced
section.

## Scope

1. Carry pending human-decision items into the renderer-only operator summary.
2. Show a `What to decide` / `判断すること` preview in the top card.
3. Show localized choice labels without exposing raw commands in the top card.
4. Give checkpoint reviews a purpose-written Japanese/English explanation
   based on their completed-feature count and threshold.
5. Fall back to the decision question, reason, or blocked reason for other
   decision types.
6. Keep `dashboard-data/v1`, SQLite schema, and detailed decision rendering
   unchanged.

## Acceptance

1. A Japanese checkpoint dashboard says that the feature threshold was reached
   and asks for a larger-goal review in the top `あなたの判断` card.
2. The same card shows `承認 / 却下 / 保留 / 追加の証跡を確認`.
3. An English dashboard shows the equivalent concise checkpoint explanation
   and choice labels.
4. A non-checkpoint decision uses its question or reason as the preview.
5. Raw `pcl` commands remain absent from the top card and available in the
   advanced details.
6. No-decision dashboards retain the existing empty-state copy.
7. Focused dashboard tests, lint, the full suite, strict validation, rendering,
   and completion-packet closure pass.

## Non-goals

- Recording, approving, or rejecting the pending decision from the dashboard.
- Automatically expanding the advanced details section.
- Translating every free-form historical reason string.
- Changing the dashboard data contract, database schema, or dependencies.
