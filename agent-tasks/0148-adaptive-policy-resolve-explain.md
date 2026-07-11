# 0148: Adaptive policy resolve and explain

- **Status:** Done; human-approved 2026-07-11
- **Milestone:** v0.4.2 Adaptive Entry
- **Priority:** P0
- **Estimated size:** L
- **Dependencies:** 0147
- **Parallel-safe with:** none
- **DB schema:** remains 8

## Goal

Resolve versioned multi-axis policy from a route recommendation and explain
the source rule for every field without changing state.

## Contract

`adaptive-policy-resolution/v1` contains policy version/hash, recommendation
Evidence/reference, input digest, resolved axes, per-field source rules,
conflicts, and reason codes. Policy source is strict JSON (`adaptive-policy/v1`)
parsed with the standard library.

Axes are planning depth, verification depth, execution chunk size, checkpoint
frequency, context budget, optional tool/time budgets, and escalation budget.

## Scope

- JSON policy schema and packaged default policy.
- Deterministic precedence: defaults -> project rules -> risk floor.
- Read-only `pcl policy resolve` and `pcl policy explain` JSON/text surfaces.
- Typed errors for unknown keys, invalid values, conflicting same-precedence
  rules, and unreadable policy.
- Per-axis provenance suitable for packet references.

## Invariants

- Invalid policy never silently falls back to defaults.
- Risk floors cannot be lowered by capability or budget signals.
- Policy change does not reinterpret historical recorded resolutions.
- No PyYAML or other runtime dependency.
- Resolve/explain are read-only.

## Acceptance criteria

Rule precedence matrix, conflict/unknown-key negatives, deterministic output,
policy hash stability, field-level explanation, JSON stdout purity, and Direct
overhead measurements pass.

## Non-goals

Override mutation, enforcement, provider pricing, model/tool execution, or
profile plugins.
