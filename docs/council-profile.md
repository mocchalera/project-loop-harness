# Council Profile operator guide

Council Profile is an opt-in adapter boundary. Project Loop Core remains the
state machine and source of truth; an external runner may only return a frozen
`profile-output-bundle/v1`. No returned command is executed automatically and
no Council artifact can approve a Brief, Story, Verification, Decision, or
release.

## Safe local flow

1. Start from a target with an approved Work Brief and a recorded route.
2. Run `pcl profile prepare`; the command is read-only and records no provider
   call.
3. Transfer only the prepared request under the approved data policy.
4. Run `pcl profile ingest ... --dry-run` before any mutation.
5. Ingest the same bytes. `completed`, `partial`, `budget_exhausted`, and
   `skipped` remain factual statuses. `needs_human` creates Decisions but never
   selects a candidate. `failed` needs explicit `--accept-failed --summary`.
6. Resolve proposal Decisions only with `pcl decision proposal select` or
   `--decline`, using explicit human provenance.
7. Run `pcl audit check`, `pcl validate --strict`, and `pcl render`.

The bundled `fixture-run` command is provider-free test data. It refuses
network, paid, or authorized requests and its output passes through exactly the
same production validators and ingest path.

## Network and paid authorization

`pcl profile authorize` records bounded human provenance and emits an
authorized request. It does not contact a provider. Scope must cover requested
providers, data class, monetary limit, and currency. Expiry is recommended.
Withdraw a receipt with:

```bash
pcl --json profile authorize --revoke EV-XXXXXXXXXXXX --actor "human:owner" \
  --recorded-by "agent:codex" --source-kind cockpit \
  --source-ref "cockpit:<task-id>" --reason "Withdraw provider scope"
```

Revocation is idempotent and immediately makes later ingest fail closed. Do not
put secrets, credentials, production data, or full transcripts in requests or
bundles. Real provider use requires separate human approval naming the exact
request hash, data classes, providers, budget, and expiry.

## Adoption boundary

Direct remains the default for clear work. Agreement is not proof, model labels
are not facts, and quality claims require a frozen comparison cohort. Changing
defaults, publishing a Profile, adding telemetry, or selecting a vendor is a
separate human decision outside this guide.
