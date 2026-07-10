# 0145: Structured validation diagnostics and repair guidance

- **Status:** Approved implementation slice
- **Milestone:** v0.4.1 Integrity Migration
- **Priority:** P1
- **Estimated size:** XL
- **Dependencies:** 0142–0144 (concrete repair commands and provenance findings must exist before diagnostics reference them)
- **Parallel-safe with:** none; this is the integration slice for validators, reports, routing, and recovery docs
- **DB schema:** remains 8

## Problem

`ValidationResult` currently exposes only `errors: [string]` and
`warnings: [string]`. Humans can read those messages, but agents must parse
unstable prose to identify the entity, related records, and safe next command.
That makes strict recovery brittle precisely when lifecycle state is already
inconsistent.

## Goal

Add deterministic structured findings at the point each diagnostic is emitted,
while retaining the existing string arrays, severities, exit codes, and
read-only validation behavior. Findings provide concrete inspection or repair
commands but never execute or semantically approve them.

## JSON contract

`pcl validate --json` and `--strict --json` retain `ok`, `errors`, and
`warnings` and add `findings`:

```json
{
  "ok": false,
  "errors": ["Done feature F-0001 has incomplete Stories: US-0001."],
  "warnings": [],
  "findings": [
    {
      "code": "feature_done_story_incomplete",
      "severity": "error",
      "message": "Done feature F-0001 has incomplete Stories: US-0001.",
      "entity": {"type": "feature", "id": "F-0001"},
      "related": [{"type": "user_story", "id": "US-0001", "status": "draft"}],
      "repair_class": "semantic",
      "requires_human": true,
      "suggested_commands": [
        "pcl story read US-0001 --json",
        "pcl repair lifecycle --dry-run --json"
      ]
    }
  ]
}
```

Finding fields are:

- stable snake-case `code`;
- effective `severity: error|warning` after strict/policy promotion;
- the exact legacy `message` also present in the matching string array;
- nullable primary `entity` and a deterministic `related` array;
- `repair_class: inspect|structural|semantic|human_review|unsupported`;
- `requires_human` based on the action's semantics, not merely severity;
- zero or more concrete, shell-quoted `suggested_commands`.

No finding is created by parsing a completed error string. Validation call
sites supply structured data and the legacy message together. Findings follow
the existing diagnostic emission order, with related entities and commands in
stable order.

## Compatibility contract

- Existing `errors` and `warnings` strings, ordering, advisory prefix behavior,
  strict promotion, CLI exit codes, and text output remain unchanged.
- `findings` is additive in validate, validation report, and strict next-action
  JSON. Consumers may continue using the legacy arrays for at least the v0.4.x
  line.
- A lifecycle advisory finding has severity `warning`; the same invariant in
  enforced policy has severity `error` without changing its code.
- Suggested commands are guidance. Validation, reports, `pcl next`, MCP, and
  dashboard generation do not execute them.

## Suggested-command safety

- Prefer read-only inspection first (`pcl ... read --json`,
  `pcl repair lifecycle --dry-run --json`, `pcl audit check --json`).
- Include a mutating repair command only when every entity ID and required
  non-semantic argument is concrete and the finding is classified structural.
- Story approval/waiver, Verification, Goal closure, Decision, and Evidence
  choice remain `semantic` or `human_review`; diagnostics may point to the
  relevant read/plan command but must not invent summaries, reasons, Evidence,
  or approvals.
- Commands use the actual v0.4.1 parser contract from 0142–0144. Do not emit
  placeholders disguised as executable commands.

## Scope

- Extend `ValidationResult` and every current validator emission path in
  `src/pcl/validators.py` with structured source data and stable codes. This
  includes installation/schema, audit, lifecycle, Evidence, relationship, and
  strict invariants; `findings` must not be a lifecycle-only partial mirror.
- Add the same finding objects to `pcl report validation` machine data and a
  readable code/entity/next-command section in its Markdown artifact.
- Keep `pcl next --strict` routing priority and command unchanged, while adding
  finding counts/codes and the validation report reference to the
  `resolve_validation_errors` action.
- Update `docs/recovery-playbook.md` to route by code and repair class.
- Add direct, snapshot, report, routing, recovery-doc, MCP/dashboard consumer,
  and backwards-compatibility tests.

## Invariants

- Validation and all diagnostic consumers remain read-only.
- Findings never become state, Evidence, Verification, or human decisions.
- Codes describe invariant classes and do not embed entity IDs or prose.
- A failure to generate safe repair guidance does not hide the diagnostic; it
  produces an empty command list or `unsupported` classification.
- HTML remains a human-only view. Machine consumers use JSON/report data.
- No schema migration, dependency, automatic repair, policy enforcement flip,
  LLM call, agent launch, or remote operation.

## Non-goals

- Removing legacy string diagnostics.
- Internationalizing every validator message.
- Turning `pcl next` into a multi-command repair executor.
- Generalizing Verification targets or changing completion-packet/v1.
- Enforcing lifecycle policy on unrepaired existing projects before dogfood.

## Acceptance criteria

- Every emitted validation error/warning has one structured finding with the
  same effective severity and exact legacy message; no orphan string or finding
  remains in the full fixture suite.
- Existing JSON/text snapshots and exit-code assertions remain valid except for
  the documented additive `findings` and strict-routing metadata.
- The synthetic false-completion fixture returns distinct stable codes for
  draft Story, missing Test Story/Evidence, done Feature gaps, and unverified
  Goal, with concrete IDs and safe inspection/repair-plan commands.
- Advisory/enforced configurations change severity, not code or entity data.
- Audit corruption, missing artifacts, and provenance drift receive distinct
  codes and appropriate inspect/unsupported guidance.
- `pcl next --strict --json` still returns `resolve_validation_errors` first and
  never runs a suggested command.
- Validation Markdown is deterministic and sufficient to follow the 0142/0143
  recovery route without parsing prose.
- Targeted validation/report/next/recovery suites, full `pytest`, `ruff check
  .`, build/fresh-wheel smoke, strict validation, and render pass.

## Evidence required to close

- Before/after compatibility fixtures showing unchanged legacy arrays plus
  additive findings.
- A code/severity/entity/repair-class matrix for representative validator
  families.
- `pcl next --strict --json` and validation-report artifacts for the synthetic
  migration fixture.
- Proof that diagnostic commands were not executed and validation caused zero
  state/artifact mutation.
