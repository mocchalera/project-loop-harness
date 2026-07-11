# Completion Policy v1

`completion-policy/v1` is a deterministic, read-only adapter between an
external tool's JSON reports and a Project Loop Test terminal transition. It
does not execute report generators or arbitrary expressions.

## Contract

```json
{
  "contract_version": "completion-policy/v1",
  "policy_id": "artifact-complete",
  "required_evidence_set_status": "complete",
  "predicates": [
    {
      "id": "findings-empty",
      "report_kind": "completion_verdict",
      "json_path": "$.findings",
      "operator": "empty"
    },
    {
      "id": "verdict-complete",
      "report_kind": "completion_verdict",
      "json_path": "$.status",
      "operator": "equals",
      "expected": "complete"
    }
  ]
}
```

Predicates are sorted and use a restricted object-key path (`$` or
`$.field.nested`). Allowlisted operators are:

- `equals`: strict JSON scalar equality;
- `in`: strict membership in a non-empty JSON array;
- `gte` / `lte`: numeric threshold, excluding booleans;
- `exists`: the path resolves;
- `empty`: the resolved value is null or an empty string/array/object.

The policy always requires an Evidence Set with `completeness=complete`.
Therefore a complete verdict cannot override a required report that was
missing, excluded, or non-passing.

## Read-only evaluation

```bash
pcl contract validate --type completion-policy/v1 completion-policy.json --json
pcl completion evaluate \
  --policy completion-policy.json \
  --evidence-set E-0003 \
  --test TC-0001 \
  --json
```

Evaluation verifies the Evidence Set artifact and exact Test target, reads only
included report kinds, rechecks every report SHA-256 against the receipt, and
returns `completion-evaluation/v1`. It writes no DB rows, links, events, files,
or consumed IDs.

## Test terminal preflight

```bash
pcl test pass TC-0001 \
  --summary "External completion contract passed" \
  --evidence-id E-0003 \
  --completion-policy completion-policy.json \
  --json
```

When `--evidence-id` has type `evidence_set`, `--completion-policy` is required.
The Evidence Set must target that exact Test, be complete, have unchanged
report hashes, and satisfy every predicate. Rejection happens before Test,
Feature, link, or event mutation. A successful transition stores the policy
hash, Evidence Set hash, predicate results, and findings-free evaluation in the
existing `test_case_passed` event. Ordinary adhoc Evidence keeps its existing
Evidence-ID-first path and does not accept `--completion-policy`.

## Story-linked planning

Fresh/enforced projects reject `pcl test plan` without `--story` before ID
allocation. Existing projects with advisory lifecycle policy still create the
planned Test, but return a structured `test_story_required` warning and a
concrete `pcl test link` command.

## Boundary

- No domain name, verdict word, threshold, or report kind is hard-coded in PCL.
- Report truth remains an external claim; PCL proves deterministic evaluation
  against hash-bound files.
- No dependency or DB migration is introduced; schema remains 8.
