# 0225: v0.6.0 practical Mainline Progress Guard

## Authority

- Human product choice: Cockpit Ask `ask_1e8d6ba6a61b`, option
  `実用Progress Guard（推奨）`.
- Implementation base: `f7f6c18cee52b4da9d5f8ac2f5a1002b089d9d78`.
- Implementation tree: `f7eea324fd11298e9406372e1c28858407b76ae6`.
- Release position: local v0.6.0 implementation candidate only. Push, tag,
  publication, deployment, and external mutation are not authorized.

## Product contract

Add one opt-in policy/runtime guard for an existing Goal and stable logical
Exit Gate. State is reconstructed deterministically from append-only schema-8
Events. Task, Run, Job, workflow, Route, model, VM, cache, dependency plan, and
artifact filename/version labels do not enter the lineage identity.

Only `criterion_closed`, `gate_bound_artifact_ready`, `human_acceptance`, and
`integrated_behavior` can record behavior-facing delta 1. Harness support,
deferred work, route/tool/environment changes, receipts, hashes, plans, and
diagnosis are zero-value observations. Two consecutive zero observations stop
normal cooperative continuation; a genuine value resets only that streak.
Consumed tokens and history remain durable.

An explicit operator replan records a reason, operator label, and new revision
token before resuming. This is an operator attestation recorded by the CLI. It
is not cryptographic proof of a human identity.

## Effect boundary

- SQLite schema remains 8; migration count remains zero.
- Runtime dependency count remains zero.
- Every guard mutation appends one Event and one transactional outbox record.
- Enforcement is limited to normal `pcl next`, `pcl start --goal`, and
  workflow Run/Job creation paths for the stopped Goal.
- No process supervisor, artifact seal, native helper, Keychain/Secure Enclave,
  CMS, telemetry, network, cloud, hosted state, external Cockpit task
  enforcement, or malicious same-UID resistance is added.
- Product status, criterion verdict, and product-red state are not mutated by
  harness-support observations.

## Verification

Behavior tests must preserve the Video OS incident fixture and a native PLH
fixture. They cover lineage alias survival, restart derivation, duplicate-token
idempotency, two-zero stop, authentic value, operator replan audit, Event/outbox
atomicity, pre-effect routing enforcement, unprotected compatibility,
deterministic JSON, version/schema/dependency invariants, and C7/finish
regressions.

The final handoff must provide exact commit/tree fingerprints and reviewable
evidence for a separately created independent review. This task does not create
its own review task.
