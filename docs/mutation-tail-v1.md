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

`pcl start ... --direct-spec ...` also returns this additive tail, with a
stricter Direct Setup consistency branch described below. Legacy `pcl start`
retains its existing `pcl-start/v1` next-actions contract. Workflow,
governance, Evidence, terminal, and unrelated entity mutations do not use the
shared tail.

An idempotent Task status request with `changed=false` returns a
`not_changed` receipt. It does not commit an event or render.

A changed Task transition to `done` first evaluates the shared
[`terminal-readiness/v1`](terminal-readiness-v1.md) receipt inside the same
authoritative `BEGIN IMMEDIATE` transaction. A typed
`task_terminal_readiness_failed` result is pre-commit: it invokes no mutation
tail and changes neither authoritative nor derived artifacts. Only a successful
Task commit reaches the existing post-commit next-action/render tail.

## Auto-render

The tail reads `dashboard.auto_render` from `pcl.yaml`.

- `true`: a meaningful connected mutation renders after the authoritative
  commit and returns artifact paths, SHA-256 hashes, sizes, and the event
  high-watermark. Each attempt reads the pre-render event watermark, renders,
  captures both artifact byte receipts, and only then reads the final
  watermark. The captured receipts are published only when both watermarks
  match. A changed watermark discards those receipts and causes one bounded
  rerender; a second change fails the tail closed without returning artifact
  hashes.
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
`recovery` fields. Text and JSON commands also emit an explicit stderr warning.
The warning uses the actual `mutation_committed` and
`safe_to_retry_original` values: a failed read-side tail after `changed=false`
does not claim that a mutation committed and reports that the idempotent retry
remains safe.

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

## Direct Setup consistency

The Direct Setup tail starts each of at most two attempts with full validation
and exact-Task projection. It checks the event high-watermark after validation,
then performs exact-target routing and checks again. Canonical dashboard files
are not changed during either phase.

- Validation drift discards that attempt. Stable validation failure stops
  immediately as `partial`, with `next_action: null`,
  `render.status: skipped_validation_failed`, no artifact hashes, and exact
  read-only target validation recovery.
- Routing drift discards the complete attempt. Two drifting attempts return
  `partial`, do not render, and return no artifact hashes.
- `changed=false` returns `not_changed` without rendering.
- With auto-render disabled, the stable receipt is `disabled`.
- With auto-render enabled, the tail acquires the existing exclusive
  project-operation lock, rechecks the same high-watermark, and only when it
  matches invokes the current canonical renderer once while the lock is held.
  That internal call is explicitly lock-held and does not reacquire the same
  advisory lock. All other canonical renderer callers—including standalone
  CLI, MCP local-render, planning, workflow execution, and the normal mutation
  tail—enter through the renderer's shared exclusive lock-aware wrapper.
  A pre-render mismatch consumes the bounded retry rather than rendering.

The Direct bundle's deterministic event anchor makes
`safe_to_retry_original=true`, while `retry_recommended=false` keeps the
read-only recovery command primary. Renderer failure is a committed partial
result with null hashes. `ProjectionPendingError` occurs before normal service
return, so it has no tail and recovers through `pcl audit flush --json`.

This contract binds the success receipt to a stable governed event watermark
and exclusive render interval. It does not claim atomic publication across the
two dashboard files or across a process crash.
