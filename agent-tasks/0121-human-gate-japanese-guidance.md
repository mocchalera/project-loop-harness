# 0121: Japanese human-gate guidance (F5)

Milestone: v0.3.1 Handoff Integrity + Operator Experience
Priority: P1
Area: cli/commands/locales
Origin: ax1-moc1 feedback F5 + Milestone 13 ("現状オール英語表記が摩擦").
Sakamoto directed proceeding 2026-07-09. Orchestrator-authored (JA copy).

## Problem

`pcl next` emits rich human-decision fields (`why_blocked`, `options`,
`recommendation`) when `requires_human` is true, but all of it is English. The
primary operator reads Japanese; the friction is the *decision branch* being in
English, not translation per se. Add an additive Japanese guidance block that
states, in Japanese: why it is blocked, what to check before deciding, and the
next options.

## Scope

- Add `HUMAN_GATE_JA` strings to `src/pcl/locales.py` (its own dict, alongside
  the existing `DASHBOARD_STRINGS` en/ja pattern; concise technical register:
  証跡 / ゴール / エスカレーション):
  - `why_blocked` by `action_type` (`record_verification`, `resolve_decision`,
    `resolve_escalation`, `open_escalation`) + a `_default`;
  - `check` (list) by `action_type` + a `_default`;
  - `option_labels`: EN label -> JA (Approve->承認する, Reject->却下する,
    Hold->保留する, Request more evidence->追加の証跡を確認する);
  - `blocking_prefix` (JA) prepended when the action is blocking.
- Add `_human_guidance_ja(*, action_type, blocking, options)` in
  `src/pcl/commands.py` returning `{why_blocked, check, next_options}`;
  `next_options` maps each existing English option label through `option_labels`.
- Wire it into `human_decision_action_fields` (commands.py) as an **additive**
  `human_guidance_ja` field, built from the already-computed `options` list.

## Invariants (what to protect)

- Additive only: existing English `why_blocked` / `options` / `recommendation` /
  `human_guidance` fields are unchanged. Existing `next` tests stay green.
- Present only for human-gated actions (inside `human_decision_action_fields`),
  never for agent-safe actions.
- No new claim vocabulary; JA text states facts and decision branches, never that
  work is correct/sufficient/safe (no 安全/検証済み-style assertions about the
  work itself).
- No schema change, no migration. Read/format only.

## Non-scope

- Localizing every CLI surface / full i18n framework. This is the `next`
  human-gate block only.
- Config-gated locale selection for `next` (always include `human_guidance_ja`
  as additive metadata for now; config-gating is a possible later refinement).
- Dashboard localization (already handled by `DASHBOARD_STRINGS`).

## Acceptance

- A human-gated `pcl next --json` (e.g. `record_verification`) includes
  `human_guidance_ja` with `why_blocked` (JA), `check` (JA list), and
  `next_options` (JA labels matching the English `options` order).
- An agent-safe next action has NO `human_guidance_ja`.
- Existing English human-decision fields and their tests are unchanged.
- `ruff` clean; full `pytest` green (baseline 502; expect > 502).
