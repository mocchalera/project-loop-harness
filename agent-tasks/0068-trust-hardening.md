# Task 0068: Trust Hardening

## Goal

Strengthen the reliability of the existing control plane before the
Explainable Code Context work begins: fix documentation drift, tighten strict
validation, replace the flat token approximation with a deterministic
character-class-aware estimator, and stabilize context pack budget accounting
so token reporting is credible.

## Scope

- Audit README and `docs/` (architecture, context-pack, dashboard-design,
  dashboard-data-contract, golden-path, data-model) against the actual CLI
  surface and JSON contracts; fix every drift found and list each fix in the
  output report.
- Strengthen `pcl validate --strict`: audit for state combinations that are
  currently accepted but inconsistent (for example dangling links, terminal
  states with open children, evidence paths that do not exist) and add
  warnings or errors for them; every new check needs a test.
- Replace the flat 4-chars-per-token approximation in `src/pcl/context.py`
  with a deterministic character-class-aware estimator (ASCII words,
  CJK characters, whitespace, punctuation). Record the estimator identity in
  pack metadata as `token_estimator` (for example `charclass/v1`) while
  keeping existing metadata fields; the change must be additive to
  `context-pack/v1`.
- Stabilize budget accounting: `omitted_sections` bookkeeping must be exact
  and deterministic under tight budgets; add regression tests for small
  `--max-tokens` values across job and task packs.
- Fix any `dashboard-data.json` versus documented contract inconsistencies
  found during the audit (additive changes only).

## Acceptance Criteria

- Repeated runs over the same state produce identical context packs and
  identical `dashboard-data.json`.
- Context pack metadata includes `token_estimator` and estimates change only
  in documented, tested ways.
- New strict validate checks fire on crafted fixtures and stay silent on the
  golden path.
- `ruff check .` passes.
- Full `python3 -m pytest` passes.
- `pcl init` smoke flow against a temp directory passes.
- No schema migration is added.
- No dependency is added.

## Do Not

- Do not add or alter tables or columns.
- Do not change contract versions; evolve `context-pack/v1` and
  `dashboard-data/v1` additively.
- Do not add embeddings, code indexing, or semantic retrieval (that is
  task 0069).
- Do not read or parse generated dashboard HTML.
- Do not use raw SQL to mutate `.project-loop/project.db`.
- Do not add hosted services, telemetry, paid services, or plugin
  distribution.
