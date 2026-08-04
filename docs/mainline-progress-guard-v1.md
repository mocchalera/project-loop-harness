# Mainline Progress Guard v1

Project Loop Harness v0.6.0 includes a practical opt-in Progress Guard for one
existing Goal and one stable logical Exit Gate. It stops normal automatic
continuation when work keeps changing execution identities without moving the
Exit Gate.

This is cooperative policy enforcement for normal PCL/Cockpit agents using
public PCL routes. It is not security-grade authorization or process
containment.

## Activate one lineage

Existing projects and Goals are unchanged until activation:

```bash
pcl progress guard activate \
  --goal G-0001 \
  --exit-gate fresh-final-render \
  --json
```

The default stagnation limit is 2. `--limit` may set an explicit value from 1
through 100 at activation. Activation is idempotent for the same Goal, Exit
Gate, and limit. A later conflicting limit is rejected rather than silently
changing policy.

The lineage identity contains only:

```text
project instance + Goal + logical Exit Gate
```

Task, Run, Job, workflow, Route label, model, VM, cache, dependency plan, and
artifact filename/version are observation metadata. Changing them never resets
the counter.

## Record observations

Every observation binds a criterion, behavior surface, stable token, reviewable
summary, evidence reference, and work classification:

```bash
pcl progress guard observe \
  --goal G-0001 \
  --exit-gate fresh-final-render \
  --delta 0 \
  --classification harness_support \
  --criterion final-render-reviewed \
  --surface video:final-render \
  --value-token render-route-c-diagnosis \
  --summary "Route C diagnosis produced no fresh final render" \
  --evidence-ref artifact:route-c-diagnosis \
  --task-label T-0054 \
  --run-label WR-0011 \
  --route-label "Route C" \
  --json
```

Classifications are closed:

- `mainline_product`
- `harness_support`
- `deferred`

Only `mainline_product` may claim delta 1, and it must use one of these closed
behavior-facing value kinds:

- `criterion_closed`
- `gate_bound_artifact_ready`
- `human_acceptance`
- `integrated_behavior`

A plan, review, receipt, hash, route/tool/model/environment change, harness
diagnosis, or backlog item is not behavior-facing value. Record it as delta 0.
`harness_support` and `deferred` are always delta 0 and cannot mark a product
criterion failed or set a product-red verdict.

Reusing a consumed value token is an idempotent duplicate. It reports effective
delta 0 without appending another observation Event or resetting state.

## Stop and replan

Two consecutive delta-0 observations at the default limit produce
`stop_and_replan`. A delta-1 observation resets only the current consecutive
zero streak. It does not remove prior observations or consumed tokens.

While stopped:

- `pcl next` returns `stop_and_replan`, marks the action unsafe for automatic
  execution, and surfaces the operator replan command;
- `pcl start --goal <guarded-goal>` rejects before creating a successor Task;
- `pcl loop run ... --goal <guarded-goal>` and workflow-backed Run/Job creation
  reject before creating a Run, Job, or prompt artifact.

This release intentionally does not install a broad mutation interceptor. It
does not block arbitrary direct database/file edits, external Cockpit task
creation, or every manual PCL mutation.

## Operator replan and resume

The operator resumes cooperative continuation with a new stable plan revision:

```bash
pcl progress guard replan \
  --goal G-0001 \
  --exit-gate fresh-final-render \
  --revision-token plan-revision-2 \
  --reason "Use the behavior-facing render path and acceptance fixture" \
  --operator operator:release-owner \
  --json
```

The command appends a visible audit Event. It clears the current stop and zero
streak, but does not erase observation counts, value events, consumed tokens,
or prior replans. The operator string and attestation are caller-supplied. They
are not cryptographic authentication of a human.

## Status contract

Status is read-only and reconstructed from Events:

```bash
pcl progress guard status \
  --goal G-0001 \
  --exit-gate fresh-final-render \
  --json
```

The `progressGuard` object uses `progress-guard/v1` and deterministically
exposes:

- lineage ID, project instance, Goal, and Exit Gate;
- active/stopped decision, limit, and consecutive-zero count;
- total observations and behavior-facing value-event count/details;
- mainline, support, and deferred counts;
- off-mainline numerator, denominator, and ratio;
- consumed tokens and last observation with Task/Run/Route labels;
- latest replan revision;
- policy-only/security-boundary statement and next action.

Each real activation, observation, or replan commits exactly one Event and one
outbox row in the same SQLite transaction. Current state uses no new table and
no migration. Restart and replay therefore reconstruct the same counters from
schema-8 Events.

## Security boundary

The guard assumes normal cooperative callers use public PCL routes. It is not
tamper-proof against a caller that edits the database or files, bypasses PCL,
or falsely supplies operator confirmation. It does not enforce external
Cockpit task creation, provide cryptographic human authentication, supervise
processes, seal artifacts, or resist a malicious same-UID agent.

Those limitations are explicit product boundaries, not deferred claims that
v0.6.0 already provides security-grade containment.
