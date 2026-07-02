# Verification Rubric

`pcl verification record` accepts optional rubric metadata for verification
decisions. Existing free-form rubric JSON remains supported. Structured
validation applies only when the rubric object declares:

```json
{"contract_version": "rubric/v1"}
```

## Command

```bash
pcl verification record --run WR-0001 --result approved --reason "Reviewed output"
pcl verification record --run WR-0001 --result approved --rubric-json '{"contract_version":"rubric/v1",...}' --reason "Reviewed output"
pcl verification record --run WR-0001 --result approved --rubric-file rubric.json --reason "Reviewed output"
pcl verification list --run WR-0001 --json
pcl verification read V-0001 --json
```

`--rubric-json` and `--rubric-file` are mutually exclusive. `--rubric-file`
must contain a JSON object. Both inputs are normalized and stored in the
existing `verifications.rubric_json` field.

## Contract

`rubric/v1` objects have this shape:

```json
{
  "contract_version": "rubric/v1",
  "acceptance_criteria": [
    {
      "criterion": "CLI rejects invalid structured rubrics",
      "met": "yes",
      "evidence_id": "E-0001"
    }
  ],
  "regression_risk": {
    "level": "low",
    "notes": null
  },
  "test_evidence": [
    {
      "evidence_id": "E-0001",
      "command": "pytest",
      "summary": "All tests passed"
    }
  ],
  "security_ux_checks": [
    {
      "check": "No secrets emitted",
      "result": "pass",
      "notes": null
    }
  ],
  "confidence_score": 0.9,
  "evidence_completeness": "complete"
}
```

Field rules:

- `contract_version` is required and must be `rubric/v1`.
- `acceptance_criteria` is required and must be a non-empty list.
- Each acceptance criterion has `criterion`, `met`, and `evidence_id`.
- `met` must be `yes`, `no`, or `unknown`.
- `regression_risk.level` must be `low`, `medium`, or `high`.
- `test_evidence` is required and may be an empty list.
- `security_ux_checks` is required and may be an empty list.
- `security_ux_checks[].result` must be `pass`, `fail`, or `n/a`.
- `confidence_score` must be a number from `0.0` to `1.0` inclusive.
- `evidence_completeness` must be `complete`, `partial`, or `missing`.
- Nullable fields accept either a string or `null`.
- `evidence_id` fields accept a non-empty string or `null`.
- Unknown top-level keys are rejected for `rubric/v1`.

When a `rubric/v1` object references evidence ids, every referenced evidence
row must already exist. Missing evidence references are rejected before the
verification is recorded.

## Inspection

`pcl verification read V-0001 --json` includes both the stored rubric JSON text
and a parsed `rubric` object:

```json
{
  "ok": true,
  "verification": {
    "id": "V-0001",
    "workflow_run_id": "WR-0001",
    "rubric_json": "{\"acceptance_criteria\":[{\"criterion\":\"Reviewed\",\"evidence_id\":null,\"met\":\"yes\"}],\"confidence_score\":0.9,\"contract_version\":\"rubric/v1\",\"evidence_completeness\":\"partial\",\"regression_risk\":{\"level\":\"low\",\"notes\":null},\"security_ux_checks\":[],\"test_evidence\":[]}",
    "rubric": {
      "contract_version": "rubric/v1",
      "acceptance_criteria": [{"criterion": "Reviewed", "met": "yes", "evidence_id": null}],
      "regression_risk": {"level": "low", "notes": null},
      "test_evidence": [],
      "security_ux_checks": [],
      "confidence_score": 0.9,
      "evidence_completeness": "partial"
    },
    "rubric_contract_version": "rubric/v1",
    "result": "approved",
    "reasons": ["Reviewed output"]
  }
}
```

`pcl verification list` is read-only and ordered by `created_at, id`.

## Validation And Reports

Normal `pcl validate` emits warnings for stored `rubric/v1` objects that no
longer satisfy the contract. `pcl validate --strict` treats invalid structured
rubrics as errors and also errors on missing referenced evidence rows.

`pcl report run WR-0001` includes a compact verification-rubric section for
`rubric/v1` records with criteria counts, regression risk, confidence score,
and evidence completeness. Free-form rubric JSON is not summarized.

## Boundaries

- No schema migration is required.
- Free-form rubric objects without `contract_version: "rubric/v1"` remain
  backward compatible.
- The command does not read or parse generated dashboard HTML.
- The feature does not change dashboard rendering or `pcl next` routing.
