# Route Recommendation v1

`route-recommendation/v1` is a deterministic, advisory decision artifact. It
uses explicit Work Brief and project signals to recommend one UX preset:

- `direct`: acceptance is clear, a deterministic check is configured, and no
  elevated-risk signal is present;
- `discover`: information or deterministic verification is missing;
- `assure`: auth/permission, migration/schema, or dependency scope raises the
  verification floor.

The recommendation is not a permission grant, model selection, or human
approval. Model self-assessment is not an input.

## Read-only default

```bash
pcl route recommend --target task:T-0001 --json
pcl route recommend \
  --target task:T-0001 \
  --changed-path src/auth/login.py \
  --json
```

The resolver uses the target's current approved Work Brief when present. A
prospective file can be inspected with `--brief`, but it remains unapproved and
therefore cannot produce Direct:

```bash
pcl route recommend --target task:T-0001 --brief draft.json --json
```

Read-only recommendation does not write DB rows, files, events, or outbox
records.

## Explicit recording

```bash
pcl route recommend --target task:T-0001 --record --json
```

`--record` writes the exact recommendation as target-linked Evidence and
appends one transactional event/outbox record. Recording the same target,
input digest, and policy version again is idempotent.

## Determinism

The input digest covers policy version, target, normalized signals, normalized
case-folded paths, and Work Brief content hash. POSIX and Windows separators
therefore resolve identically. Output has no timestamp; identical normalized
input is byte-equivalent canonical JSON.

Stable reason codes currently include:

```text
auth_or_permission_change
clear_acceptance
contradicted_assumption
dependency_change
migration_change
missing_acceptance
missing_work_brief
no_deterministic_check
unapproved_brief_input
unverified_assumption
```

Policy axes and override are intentionally deferred to tasks 0148 and 0149.
