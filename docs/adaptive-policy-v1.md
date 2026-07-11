# Adaptive Policy v1

`adaptive-policy/v1` resolves a deterministic route recommendation into
independent execution-control axes. It is strict JSON, not YAML, so the core
runtime remains standard-library only.

## Read-only commands

```bash
pcl policy resolve --target task:T-0001 --json
pcl policy explain --target task:T-0001
pcl policy resolve \
  --target task:T-0001 \
  --policy project-policy.json \
  --changed-path src/auth/login.py \
  --json
```

Resolve and explain do not write DB rows, files, events, or outbox records.

## Precedence

```text
defaults -> profile preset -> matching project rules -> risk floor
```

Every resolved axis carries its source rule. If two matching project rules set
different values for the same axis, resolution stops with
`adaptive_policy_rule_conflict`; list order is not used as a hidden tie-breaker.

Resolved axes are:

- planning depth;
- verification depth;
- execution chunk size;
- checkpoint frequency;
- context byte budget;
- optional tool-call and wall-time budgets;
- escalation budget.

## Risk floors

R2 requires at least independent verification. R3 additionally requires small
execution chunks and high checkpoint frequency. R4 requires human
verification. A custom policy that weakens these floors is invalid before
resolution.

## Packaged policy

The default policy is shipped as
`pcl/contracts/policies/adaptive-policy-v1-default.json`. The resolution output
includes both `policy_version` and canonical `policy_sha256`, so later policy
changes do not reinterpret an already captured result.

## Explicit audited override

```bash
pcl route override \
  --target task:T-0001 \
  --profile assure \
  --actor "human:owner" \
  --reason "Require an independent review" \
  --dry-run --json

pcl route override \
  --target task:T-0001 \
  --profile assure \
  --actor "human:owner" \
  --reason "Require an independent review" \
  --json

pcl route current --target task:T-0001 --json
```

Preview is zero-mutation. Apply stores the original recommendation and
original policy resolution as separate Evidence, then records a
`route-override/v1` artifact with hash-bound references to both. The three
Evidence rows, three links, one domain event, and one outbox record commit in a
single transaction; the same semantic request is idempotent.

Permission, migration, destructive-operation, human-review, and R4 route
floors cannot be downgraded. Policy risk floors are applied again to the
effective profile. Historical effective resolution is embedded in the
override, so later policy file changes do not reinterpret it.

Task context exposes `adaptive-route-context/v1`; completion packets include
the same optional hash-bound metadata; resume handoff context references include
the override and its original Evidence artifacts. Older packet fixtures remain
valid because these fields are additive.

Neither read-only resolution nor explicit override is permission or human
approval for a separate guarded operation.
