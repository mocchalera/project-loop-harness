# Task 0083: Required Section / Truncation Invariant (P0)

## Goal

Context packs must never silently drop safety-critical sections or the
truncation notice. Today `_render_with_budget` in `src/pcl/context.py`
selects sections purely by priority within `--max-tokens`: at a small
enough budget, even priority-10000 sections (`machine_context_rules`,
`code_context_safety`) are silently omitted, and the
`_Context truncated..._` note itself is dropped when it does not fit
(context.py, `_render_with_budget` tail). A control plane must not
return a "successful" pack whose body is missing its safety facts or
missing any indication that content was cut.

Turn "highest priority" into an invariant: required sections are
either present in the Markdown body, or the command fails with a typed
error. Same for the truncation note whenever anything was omitted.

## Design constraints (agreed, do not relitigate)

- `machine_context_rules` is ALWAYS required, for every pack kind
  (job and task) and every role profile.
- `code_context_safety` is required whenever `--include-code-context`
  is passed (i.e. whenever the section exists in the canonical section
  list).
- If a required section cannot fit within `--max-tokens`, the command
  MUST NOT return a successful pack. It raises a typed error.
- If `omitted_sections` is non-empty, the truncation note MUST be
  present in the Markdown body. Budget for the note is reserved up
  front when any omission occurs; if even required sections + note do
  not fit, that is the same typed error.
- No schema migration, no new runtime dependency. `context-pack/v1`
  evolves additively only (new metadata fields are allowed; existing
  fields keep their meaning).
- Behavior with an ample budget is unchanged: existing green-path
  outputs stay byte-stable except for the documented additive
  metadata fields.

## Scope

### 1. Typed error

- Add a `ContextPackBudgetError` (follow `src/pcl/errors.py`
  conventions) with `code: "context_pack_budget_too_small"` and
  usage-style exit code (`EXIT_USAGE`, consistent with other
  caller-fixable input errors — confirm against how `--max-tokens < 1`
  is handled today and stay consistent).
- `details` must carry, at minimum: `required_sections` (ids),
  per-required-section estimated token counts, the requested
  `max_tokens`, and an `estimated_min_max_tokens` hint (title +
  required sections + truncation-note reserve) so the caller knows
  what budget to retry with.

### 2. Selection algorithm change

- In `_render_with_budget` (or a wrapper), required section ids are
  selected first, unconditionally, before priority-ordered selection
  of the remaining sections.
- When at least one non-required section is omitted, reserve the
  truncation-note tokens BEFORE filling remaining budget with optional
  sections, so the note can never be crowded out by an optional
  section.
- Priority ties: `machine_context_rules` and `code_context_safety`
  share priority 10000 today. With this change the tie no longer
  matters for them (both are required), but keep the deterministic
  tie-break (canonical order) for optional sections.

### 3. Pack metadata

- Add `required_sections` (list of section ids) to the pack payload
  for both job and task packs.
- Add `required_sections_omitted` (always `[]` on success — present
  for machine readers so the invariant is visible in the contract, and
  documented as such).

### 4. Documentation

- `docs/context-pack.md`: replace the "pinned at the highest section
  priority" description with the invariant semantics: required
  sections are guaranteed present on success; too-small budgets fail
  with `context_pack_budget_too_small`; the truncation note is
  guaranteed whenever `omitted_sections` is non-empty.

## Acceptance Criteria

- Tiny-budget pack WITHOUT `--include-code-context`: either succeeds
  with `machine_context_rules` present in the Markdown body, or fails
  with `context_pack_budget_too_small`; never a success whose body
  lacks `machine_context_rules`.
- Tiny-budget pack WITH `--include-code-context`: same invariant for
  BOTH `machine_context_rules` and `code_context_safety`.
- Explicit test for the former tie case: a budget sized so that only
  one of `machine_context_rules` / `code_context_safety` would fit
  under the old algorithm now produces the typed error (this is the
  regression test for the old silent-drop of `code_context_safety`).
- Truncation note invariant: for every successful pack with non-empty
  `omitted_sections`, the note string is present in `markdown`
  (property-style test across a range of budgets is acceptable).
- A budget that fits required sections but not the note (when
  something is omitted) produces the typed error, not a noteless
  truncated pack.
- Error `details` include `estimated_min_max_tokens`, and retrying
  with that value succeeds (test this round-trip).
- Ample-budget regression: existing fixture packs are unchanged except
  `required_sections` / `required_sections_omitted` additions.
- JSON error output follows the standard `ok:false` typed-error shape.
- `ruff check .` passes; full `python3 -m pytest` passes (372 green
  today, plus new tests); `pcl init` smoke against a temp dir passes.

## Do Not

- Do not change section priorities, role profiles, or canonical order
  for optional sections.
- Do not make `code_context_detail` or
  `code_context_verification_suggestions` required — they remain
  budget-eligible.
- Do not add `safe_to_continue` or any go/no-go field.
- Do not use raw SQL to mutate `.project-loop/project.db`.
- Do not add hosted services, telemetry, or new runtime dependencies.
