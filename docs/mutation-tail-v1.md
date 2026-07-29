# P0-A mutation-tail/v1

`mutation-tail/v1` is an additive post-commit contract for selected public
mutations. Domain services still own the authoritative transaction, event, and
outbox commit. The tail runs only after that service returns successfully.

## Connected Direct surfaces

- `pcl feature add ... --task T-XXXX`
- `pcl task status T-XXXX <status> --reason ...`

Both surfaces have an exact Task target. Their JSON result adds
`mutation_tail` with:

- `mutation_committed` and `safe_to_retry_original`;
- exact-target `next_action`, using the same router as `pcl next --target`;
- a `render-receipt/v1` result;
- read-only recovery when next-action or render work fails after commit.

Other mutation handlers are intentionally unchanged in P0-A. `pcl start`
retains its existing `pcl-start/v1` next-actions contract, and Workflow,
governance, Evidence, terminal, and unrelated entity mutations do not yet use
the shared tail.

An idempotent Task status request with `changed=false` returns a
`not_changed` receipt. It does not commit an event or render.

## Auto-render

The tail reads `dashboard.auto_render` from `pcl.yaml`.

- `true`: a meaningful connected mutation renders after the authoritative
  commit and returns artifact paths, SHA-256 hashes, sizes, and the event
  high-watermark. The renderer is bracketed by read-only event watermark
  reads. A changed watermark causes one bounded rerender; a second change
  fails the tail closed without returning artifact hashes.
- `false` or a missing setting: no render occurs.
- invalid configuration or render failure: the mutation remains committed,
  `safe_to_retry_original=false`, and recovery is the exact read-only command
  `pcl validate --target <T-XXXX|G-XXXX> --summary --json`.

The tail appends no event. Rendering changes only derived dashboard artifacts.
Successful receipts include a `consistency` proof whose before/after
high-watermarks are equal to the receipt watermark.

Post-commit failures preserve top-level `ok=true` and exit zero for the
authoritative mutation. They add top-level `mutation_committed`,
`safe_to_retry_original`, `post_commit_status`, `post_commit_diagnostics`, and
`recovery` fields. Text and JSON commands also emit an explicit stderr warning
that the original mutation must not be retried.

`dashboard.auto_render` is validated as a global configuration finding.
Selected mutation services allow only that post-commit configuration finding
through their initialization guard so the authoritative mutation can commit;
the tail then reports the partial outcome and read-only recovery diagnoses the
persistent configuration error.

## Validation projection

`pcl validate` still evaluates the entire project before applying
`--target`, `--active-only`, or `--summary`.

Projected JSON preserves the full verdict and legacy full finding counts. It
adds:

- `full_validation`, containing deterministic digest and full totals;
- `validation_projection`, containing the exact target, detailed count, and
  omitted/historical code aggregates.

Historical messages are aggregated rather than returned as detailed findings.
Target projection keeps exact-target active findings plus all active errors,
global integrity/configuration findings, unknown/unsupported findings, and
human-required gates. Active agent registry, lease, and concurrency safety
findings are an explicit global operational-safety family and retain their full
detail.

Target resolution opens an existing database through a query-only SQLite URI.
When the database or routing tables are missing, projection preserves the full
validation findings and returns a typed
`validation_target_resolution_unavailable` result without creating files.
Missing or malformed Task/Goal targets in a valid database still fail closed.

With no projection flags, JSON keys, text output, ordering, strict behavior,
and exit status retain the previous contract.
