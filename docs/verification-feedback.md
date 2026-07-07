# Verification Feedback

`pcl verification feedback` records caller feedback for a suggestion emitted in
a context receipt. Suggestion IDs include `/`, so quote them in shells:

```bash
pcl verification feedback --suggestion 'E-0001/VS-01' --status executed \
  --result passed --evidence E-0009
```

The command lives under the existing `verification` namespace. There is no
`pcl verify` alias.

## CLI Contract

Required fields:

- `--suggestion`: a receipt suggestion ID such as `'E-0001/VS-01'`.
- `--status`: one of `executed`, `skipped`, or `not_applicable`.

`executed` requires both `--result` and `--evidence`. `--result` must be one of
`passed`, `failed`, or `inconclusive`. `skipped` and `not_applicable` must not
include `--result`. If `--evidence` is supplied, it must reference an existing
evidence row.

Before inserting a row, PLH resolves the receipt evidence ID from the suggestion
prefix, loads that receipt artifact, and checks that the suggestion ID is present
in the receipt payload. These are distinct typed failures:

- unknown receipt evidence;
- unreadable receipt artifact;
- suggestion ID absent from the receipt.

Each accepted feedback command appends one row to `verification_feedback` and
one JSONL audit event. Multiple rows for the same suggestion are allowed.

## Stats Contract

`pcl verification stats --json` is read-only. It scans evidence rows with
`type = 'context_receipt'`, loads receipt artifacts, and joins addressable
suggestions to `verification_feedback`.

Addressable suggestions are object-form suggestions with a non-null `id`.
Legacy string-form suggestions are excluded from every denominator and reported
as `unaddressable_legacy_suggestions_count`.

Suggestion-level rates use addressable issued suggestions as the denominator:

- `feedback_coverage_rate`: suggestions with at least one feedback row divided
  by addressable issued suggestions.
- `execution_rate`: suggestions with at least one `executed` feedback row
  divided by addressable issued suggestions.

Feedback-event-level rates use executed feedback events as the denominator:

- `executed_pass_rate`: executed feedback events with `result = 'passed'`
  divided by executed feedback events.
- `executed_fail_rate`: executed feedback events with `result = 'failed'`
  divided by executed feedback events.

Empty denominators produce `null`, not `0.0`. The JSON includes the raw
numerator and denominator for every rate, plus `receipts_scanned`,
`receipts_unreadable_count`, and warnings for unreadable receipt artifacts.
Unreadable artifacts are counted and reported; stats does not invent suggestion
zeros for artifacts it cannot load.

## Supporting Evidence Health

`pcl verification stats --json` also reports a derived
`supporting_evidence_health` section. This is a current-time reviewability check
for evidence referenced by feedback rows. It does not rewrite feedback rows or
change rate numerators, denominators, or formulas.

Health values are:

- `ok`: the referenced adhoc manifest and reviewable member artifacts are
  readable today. For copied adhoc members, this means the stored copy is
  readable; original source churn can still appear as informational
  `source_drifted` findings.
- `warning`: the adhoc manifest is readable, but a reference-mode member is
  missing or hash-drifted, or a copied member's stored copy is missing or
  hash-drifted.
- `error`: the referenced evidence row or adhoc manifest cannot be reviewed in
  the expected shape.
- `unknown`: v0 does not assess this evidence type.

The v0 scope is limited to `adhoc_artifact` and `adhoc_bundle` evidence. Other
supporting evidence types, such as context receipts or command-result rows, are
reported as `unknown` with a finding that names the evidence type.

Health is about current reviewability of referenced artifacts, not whether the
original caller claim was true or false. PLH records feedback append-only; a
later health change is reported as a separate observation.

## Epistemic Boundary

`executed` and `result` are caller claims backed by the referenced evidence
pointer. PLH stores the claim, links it to receipt evidence, and reports
observable rates. PLH does not independently confirm that a suggested command
ran or that the caller's result is correct.
