# Council Profile contract freeze v0.5.0

**State:** Proposed, pending the ADR-005 human outcome  
**Runtime dependency delta:** none  
**SQLite schema:** 8, unchanged

## Canonical JSON and digests

All digests use UTF-8 JSON with `ensure_ascii=false`, `allow_nan=false`,
lexicographically sorted object keys, compact separators, and no trailing
newline. Duplicate keys and non-finite numbers are invalid.

- Artifact digests hash exact file bytes.
- `profile.manifest_sha256` hashes the exact UTF-8 bytes of the selected
  manifest file, including its final newline. It is not a canonical-JSON hash.
- `bundle_digest` hashes the canonical bundle after removing
  `/bundle_digest`.
- `request_digest` hashes the canonical request after removing
  `/request_digest`.
- `request_basis_digest` hashes the canonical request after removing exactly
  `/generated_at`, `/authorization`, `/request_digest`,
  `/request_basis_digest`, `/context/receipt_age`, and
  `/context/age_warning`.
- Unknown time-derived fields are rejected by `additionalProperties=false`;
  implementations must not silently strip unknown fields.

Underlying receipt timestamps, source references, artifact hashes, included
sections, omitted sections, target, Work Brief, route, policy, budgets,
providers, and data policy remain in the request basis. A semantic change
therefore invalidates prior authorization. The candidate and authorized
fixtures intentionally differ in generation time and receipt-age presentation
but share one basis digest.

`request_id` remains in the request basis. Authorized re-prepare must reuse
the bound candidate's `request_id`; it must not allocate a new timestamped ID.
The final `request_digest` changes because authorization is embedded, while
the basis and identity remain stable.

## Project fingerprint

`project.root_fingerprint` is SHA-256 over canonical JSON containing:

1. resolved absolute project root;
2. `project.name`;
3. `project.type`;
4. current SQLite schema version;
5. Git HEAD, or `null` when unavailable.

Only the digest and `root_basename` are emitted. The absolute root never
appears in the request. Moving a project intentionally changes the fingerprint.
This digest is an opaque correlation guard, not authentication or a secret.
Its low-entropy inputs could permit a targeted dictionary attack, so operators
must treat it as metadata allowed by the request data policy. HMAC was
considered and deferred because a new secret lifecycle would violate the
read-only/schema-8 MVP boundary; revisit before exposing fingerprints beyond
an explicitly authorized runner.

## Terminology

| Concept | Public JSON field | Example |
|---|---|---|
| Direct/Discover/Assure routing preset | `route_profile` | `discover` |
| External runner contract | `runner_profile_id` | `council.discovery` |
| Context-packing role | `role_profile` | `default` |

CLI help, JSON, and error codes must keep these nouns distinct.

## Authorization binding

Offline, non-paid requests use `authorization: null`. Network or paid
requests are not runnable without an embedded `approval-provenance/v1`
receipt whose:

- `actor_kind` is `human`;
- target equals the request target;
- `request_basis_digest` equals the recomputed basis;
- bound Evidence is the immutable candidate request;
- provider, cost, data-class, expiry, and revocation scope covers the request;
- mediated recording uses conversation or Cockpit provenance.

Authorization never executes a runner. The mismatch fixture changes
`route_profile` after authorization and must fail with
`profile_authorization_basis_mismatch`.

When `recorder_kind` differs from `actor_kind`, semantic validation requires
`source_kind` to be `conversation` or `cockpit` and a non-empty
`source_ref`. JSON Schema shape validation alone is not sufficient.

Authorization data-class coverage is exact:

| Request `repository_content_policy` | Required authorization data class |
|---|---|
| `none` | `metadata` |
| `selected_snippets` | `selected_snippets` |
| `full_allowed` | `full_repository` |

`network_access=requested` requires an authorization receipt.
`paid_service_requested=true` additionally requires non-null cost/currency
scope and request providers must be a subset of authorized providers.

## Cross-reference rules

- Every bundle artifact ID and normalized relative path is unique, including
  case-folded path uniqueness on case-insensitive platforms.
- Bundle paths are POSIX relative paths, contain no empty, `.`, or `..`
  segment, and resolve beneath the bundle root. Symlinks are invalid.
- Artifact role, media type, and contract version must agree.
- `decision_proposal_artifact_ids` references only listed
  `decision_proposal` artifacts and contains at most three IDs.
- `needs_human` contains one to three proposal IDs and a human-decision next
  action. `failed` contains none.
- Each proposal recommendation references an existing candidate; candidate IDs
  are unique and there are two to five candidates.
- Claim verification refs resolve inside the verification plan; participant
  refs resolve inside the Council run; every artifact run/request ref agrees.
- Request ID/digest, runner Profile ID/version, and manifest hash agree across
  request, bundle, and run manifest.

## Status boundary

`completed`, `needs_human`, `partial`, `budget_exhausted`, `failed`,
and `skipped` describe runner output only. None is execution-ready.
`next_action.safe_to_run` is therefore always the literal `false`; it is not
an external-runner execution permission.
`failed` requires the later explicit `--accept-failed` mutation.

## Claim-to-proof mapping

| Claim kind | Allowed PLH destination | Forbidden promotion |
|---|---|---|
| `fact` | ordinary Evidence followed by deterministic, observational, or human verification | direct proof-level increase |
| `assumption` | Work Brief assumption, verification proposal, or unverified completion claim | Test pass or completion |
| `inference` | verification proposal or unverified completion claim | deterministic Evidence |
| `preference` | human Decision or human-approved Work Brief | agent/model approval |
| `risk` | verification plan, residual risk, or escalation | silent dismissal |

No Council artifact can directly approve a Work Brief, pass a Test, complete a
Feature, close a Goal, or raise a `completion-packet/v1` proof level.

## Compatibility and supersession

The earlier integrated-roadmap `decision-proposal/v0` was unshipped. This
freeze supersedes its `id/work_brief_ref/hypothesis/tradeoffs/producer` shape
with the Council `proposal_id/run_ref/target/benefits/costs/generated_by`
shape. The roadmap schema, example, and semantics note are updated together;
there is only one documented shape under this version.
