# Context Check

`pcl context check` is a read-only preflight for target-bound handoff context.
It reports facts for one task or agent job without running `pcl index build`,
without running `pcl impact`, and without writing evidence, events, links, or
artifacts.

## Command

```bash
pcl context check --task T-0001 --json
pcl context check --job J-0001 --json
```

Use `--require-bound-receipt` when a script should fail unless a matching
target-bound code-context receipt exists:

```bash
pcl context check --task T-0001 --require-bound-receipt --json
```

## JSON Payload

JSON mode returns:

```json
{
  "ok": true,
  "context_check": {
    "target": {"type": "task", "id": "T-0001"},
    "supporting_evidence_count": 0,
    "target_bound_code_context": {
      "status": "missing"
    },
    "canonical_context_pack_command": "pcl context pack --task T-0001 --include-code-context --require-bound-receipt --json",
    "recommended_refresh_command": "pcl impact --diff --for-task T-0001 --json",
    "warnings": ["No target-bound code context receipt exists for this task."]
  }
}
```

`target_bound_code_context.status` is one of:

- `present`: a `code_context` evidence link points to a `context_receipt`
  artifact whose `target_binding` matches the requested target.
- `missing`: no `code_context` link exists for the target.
- `mismatched`: a `code_context` link exists, but the receipt artifact's
  `target_binding` disagrees with the requested target or is missing.
- `unavailable`: a `code_context` link exists, but the target binding could not
  be confirmed from the evidence artifact.

When status is `present`, `target_bound_code_context.receipt_ref` contains
`evidence_id` and `created_at`. When status is `mismatched`,
`target_bound_code_context.claimed_target_binding` reports the artifact's
claimed binding.

`recommended_refresh_command` is included when status is `missing`,
`mismatched`, or `unavailable`. The canonical strict handoff command is always
reported as `canonical_context_pack_command`.

## Exit Codes

- Default mode exits `0` when the diagnostic runs, even when status is not
  `present`.
- A malformed or absent task/job id raises the same typed `impact_target_*`
  error used by `pcl impact --for-task` and `pcl impact --for-job`, exiting `2`.
- With `--require-bound-receipt`, `missing` and `unavailable` raise
  `context_pack_bound_receipt_required`, exiting `2`.
- With `--require-bound-receipt`, `mismatched` raises
  `context_pack_bound_receipt_mismatch`, exiting `2`.

The command reports only what exists in the local harness state and receipt
artifact. It does not judge sufficiency, relevance, or whether work should
continue.
