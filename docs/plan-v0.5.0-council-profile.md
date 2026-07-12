# v0.5.0 Council Profile implementation plan

**Status:** Direction approved; implementation starts with ADR/contract freeze
**Approved direction:** 2026-07-12, Cockpit human selection
**Baseline:** `main` at `0eb3273`, PLH `0.4.3`, SQLite schema 8
**Source handoff:** `/Users/mocchalera/Downloads/plh-council-handoff-2026-07-11.zip`

## Outcome

PLH will remain the model-independent System of Record and control plane while
an optional external runner performs model/provider-specific discovery. PLH
will prepare a deterministic request, validate a typed output bundle, preserve
it as immutable Evidence, and reduce unresolved value judgments to existing
human Decisions. PLH will not call a provider, store credentials, or treat
model agreement as deterministic proof.

The milestone succeeds when an offline fixture can complete this path in a
source checkout, wheel, and sdist install:

```text
Work Brief + effective route + policy
  -> read-only profile request
  -> external offline runner
  -> deterministic dry-run validation
  -> atomic Evidence ingest
  -> 0..3 existing Decisions
  -> hash-bound human selection
  -> separately reviewed/approved Work Brief revision
```

## Approved product decisions

1. Ship the Profile boundary in **v0.5.0 Discovery Profile**, not v0.4.x.
2. MVP discovers **built-in, data-only manifests only**. External manifest
   directories, trust allowlists, signing, and marketplace behavior are later
   work.
3. A valid `needs_human` bundle atomically creates one existing Decision per
   proposal, up to three. There is no second Option/Proposal state store.
4. Paid or network-enabled requests require hash-bound human approval
   provenance. Project config alone cannot grant that authority.
5. A `failed` bundle is dry-run inspectable but requires explicit
   `--accept-failed` plus `--summary` to persist. It never becomes
   execution-ready.
6. A production multi-model runner belongs in a separate package/repository.
   Creating or publishing it is a later explicit human-approved action.
7. `pcl profile` remains the public command. Help text, JSON fields, and error
   codes must distinguish runner Profile IDs from route and role profiles.
8. Council Profile delivery and Adoption/Distribution release readiness are
   separate tracks. Tasks 0154–0162 close the Council feature track; README
   split, stability policy, and publication readiness receive separate tasks.

## Scope

### PLH Core

- Seven versioned, standard-library-validated contracts.
- Built-in profile list/show/validate surfaces.
- Deterministic, read-only `pcl profile prepare`.
- Fail-closed bundle validation and dry-run planning.
- Atomic bundle copy, Evidence/link/event mutation, replay idempotency, and
  bundle-ID conflict detection.
- Decision proposal projection and human-provenance selection.
- Offline fixture runner, distribution smoke, dogfood, and adoption metrics.

### External runner boundary

- Provider SDKs, credentials, retry/rate limits, model capability registry,
  participant selection, prompts, topology, cost, latency, and privacy
  reporting stay outside `src/pcl`.
- PLH only publishes request/output contracts and an invocation hint; it does
  not import or execute runner code.

### Non-goals

- No database migration, ProfileRun/Claim/Option tables, hosted backend,
  telemetry, cloud sync, automatic provider calls, arbitrary executable
  plugins, automatic verification commands, rich Council UI, or full
  transcript/hidden chain-of-thought retention.
- Council is opt-in for `discover` and selected `assure` work. It is not added
  to the clear-task Direct path.

## Terminology and contract freeze rules

- **route profile** means the existing `direct | discover | assure` UX preset.
- **runner Profile ID** means a data-only adapter contract such as
  `council.discovery`. Fields and errors must not overload these concepts.
- Public JSON uses `route_profile` for Direct/Discover/Assure,
  `runner_profile_id` for `council.discovery`, and `role_profile` for context
  packing. `pcl profile --help` and all error messages use the same nouns.
- The existing `docs/roadmap/integrated` `decision-proposal/v0` is an unshipped
  planning draft, not a runtime/public contract. Task 0154 will explicitly
  supersede that draft with the richer Council shape before runtime freeze and
  update its example and references atomically. No silent dual shape is
  allowed under the same contract version.
- Runtime validation follows current PLH convention: packaged JSON Schema plus
  explicit Python validators using the standard library. `jsonschema` does not
  become a runtime dependency.
- Canonical JSON is UTF-8, `ensure_ascii=False`, `allow_nan=False`, sorted keys,
  compact separators for digests, and no trailing newline in the digest input.
  Self-digest fields are omitted before hashing.
- `profile-run-request/v1` has a `request_basis_digest` computed without its
  authorization, final request-digest, and presentation-time fields. The
  schema freezes exact excluded JSON pointers: top-level `generated_at`,
  `authorization`, and `request_digest`, plus context `receipt_age` and
  `age_warning` projections. Underlying receipt timestamps, hashes, selected
  sections, and source refs remain bound. Unknown derived-time fields fail
  contract tests instead of being silently dropped. This gives paid/network
  human approval a stable, non-circular hash target.

`project.fingerprint` is `sha256` over canonical JSON containing the resolved
absolute project root, `project.name`, `project.type`, current SQLite schema
version, and Git HEAD when available. Only the digest and non-sensitive project
basename are emitted; the absolute root never leaves the local digest input.
Moving the project intentionally invalidates old runner output.

The frozen contract set is:

| Contract | Purpose |
|---|---|
| `profile-manifest/v1` | Static data-only capabilities and contract support |
| `profile-run-request/v1` | Hash-bound PLH state handed to a runner |
| `profile-output-bundle/v1` | Atomic list of returned artifacts |
| `council-run/v0` | Participants, topology, budget, privacy, and stop reason |
| `claim-set/v0` | Fact/assumption/inference/preference/risk separation |
| `verification-plan/v0` | Proposal-only, never auto-executed checks |
| `decision-proposal/v0` | Two to five options for one human question |

## Fit to the current implementation

| Required behavior | Current reusable surface | Required adaptation |
|---|---|---|
| Contract packaging | `src/pcl/contracts/*` and package schema tests | Add one validator module per contract and exports |
| Brief resolution | `work_briefs.show_work_brief` and hash-bound approval events | Allow one healthy unapproved candidate for Discovery; require `--brief` on ambiguity |
| Route/policy | `route_overrides.current_route`, `adaptive_policy.resolve_policy_for_target` | Serialize original/effective route and hashes without recording a route |
| Context | `context.pack_context_for_task/job` | Add a machine payload adapter; do not parse dashboard HTML |
| Evidence durability | `evidence.py` staging, hashing, links, outbox events | Add directory-bundle atomic copy/re-hash; adhoc Evidence permits outside-root sources by default but has different semantics |
| Decision state | `decisions.py` and `approval_provenance.py` | Add connection-scoped open/resolve helpers so Evidence, links, Decisions, and events share one transaction |
| Proposal binding | `evidence_links` plus immutable events | Link bundle Evidence to each Decision and bind proposal path/hash in event payload; no new columns |
| Next action | existing open-Decision priority in `pcl next` | Return the created Decision IDs and reuse current routing |
| Audit recovery | `audit._check_evidence` recognizes only current artifact families | Add Profile bundle orphan detection and report-only/quarantine guidance |

Evidence table rows do not have a generic metadata column. Profile/request/
bundle metadata therefore lives in the immutable bundle Evidence manifest and
the `profile_output_ingested` event, not in invented row fields.

## CLI contract

```bash
pcl profile list [--json]
pcl profile show council.discovery [--json]
pcl profile validate council.discovery [--json]
pcl profile prepare council.discovery \
  --target task:T-0001 [--brief E-0007] [--output request.json] [--json]
pcl profile authorize \
  --request candidate-request.json --actor human:owner --actor-kind human \
  --max-cost <amount> --allowed-provider <id> --data-class <class> \
  [--recorded-by agent:codex --recorder-kind agent] \
  [--source-kind cockpit --source-ref <receipt>] --reason <text> [--json]
pcl profile ingest \
  --request request.json --bundle output/profile-output-bundle.json \
  --dry-run [--json]
pcl profile ingest \
  --request request.json --bundle output/profile-output-bundle.json \
  --summary "Council discovery result" [--accept-failed] [--json]
pcl decision proposal show DEC-0004 [--json]
pcl decision proposal select DEC-0004 \
  --candidate OPT-A --actor human:owner --actor-kind human \
  [--recorded-by agent:codex --recorder-kind agent] \
  [--source-kind cockpit --source-ref <receipt>] \
  --reason <text> [--override-reason <text>] [--json]
```

`prepare`, `list`, `show`, `validate`, proposal `show`, and ingest `--dry-run`
are read-only. `prepare --output` may write only the explicitly named file.
External commands and commands inside a verification plan are never executed.

### Paid/network authorization handshake

Offline requests need no extra mutation. When requested data policy enables
network access or a paid service:

1. `profile prepare` computes and returns a candidate request plus its
   `request_basis_digest`, but returns `human_required` while authorization is
   absent.
2. After task 0159, the human may run `pcl profile authorize --request
   <candidate> ...`. This explicit mutation copies the candidate request as
   immutable Evidence and appends a `profile_run_authorized` event containing
   existing `approval-provenance/v1`, approved provider/data classes, maximum
   cost, and expiry/revocation conditions.
3. `profile prepare --authorization-event <EVT-ID>` rebuilds the current basis,
   verifies the Evidence hash, event, actor/source provenance, scope, and
   expiry, then embeds the factual authorization receipt and computes the final
   request digest.
4. Any target, Brief, route, policy, context, budget, provider, or data-policy
   change changes the basis digest and invalidates the authorization.

Candidate and authorized prepare calls may run at different wall-clock times.
Both compute the same basis from the normalized context projection; receipt age
remains display metadata and cannot invalidate authorization by itself.

The authorization action does not run the external command. An agent recorder
may record a human choice only with conversation/Cockpit source provenance.

## Atomic ingest design

Validation and mutation are separate phases.

1. Open request and bundle files with size limits and duplicate-key rejection.
2. Validate request schema/digest and current project/target binding.
3. Validate manifest ID/version/hash, bundle schema/status/digest, path rules,
   file count/aggregate bytes, symlinks, hashes, artifact schemas, and cross
   references.
4. Produce a deterministic dry-run plan containing exact mutation counts.
5. For a real ingest, copy listed files into a private temporary Evidence
   directory and re-hash every staged byte.
6. Begin one SQLite mutation transaction.
7. Allocate and insert one `profile_output_bundle` Evidence row and its target
   evidence link.
8. For `needs_human`, allocate and insert 1..3 existing Decision rows and
   Evidence-to-Decision links using the same connection.
9. Append `decision_opened` events and one `profile_output_ingested` event via
   the existing transactional outbox path.
10. Atomically rename the staged directory to its final immutable path, then
    commit. On ordinary failure, roll back and remove the final directory; a
    process crash after rename/before commit leaves an orphan that the Profile
    extension to the existing audit path must detect.

Any failure before commit leaves zero Evidence, links, Decisions, or events and
removes staging files. Exact `bundle_id + bundle_digest` replay returns the
original Evidence/Decision IDs with zero mutation. Reusing the bundle ID with a
different digest fails closed. Replay/conflict lookup scans committed
`profile_output_ingested` event payloads and verifies the referenced immutable
manifest; it does not depend on an unapproved metadata column or SQLite JSON
extension.

Proposal-linked Decisions are identified by their Evidence link and immutable
open event. Legacy `pcl decision resolve` and `pcl decision waive` remain
compatible for ordinary Decisions, but reject proposal-linked Decisions with
`decision_proposal_command_required`. Only `pcl decision proposal select` or a
future equally provenance-bound command may close that gate.

## Claim-to-proof boundary

`claim-set/v0` is discovery input to later work, not a completion proof model.

- `fact` remains a claim until normal PLH services resolve and verify its
  deterministic, observational, or human Evidence.
- `assumption` and `inference` flow to Work Brief assumptions, verification
  proposals, or completion packet unverified claims; they never raise proof
  level automatically.
- `preference` flows only to a human Decision or approved Work Brief.
- `risk` flows to verification planning, residual risk, or escalation.
- No Council claim directly passes a Test, completes a Feature, closes a Goal,
  or changes `completion-packet/v1` proof level.

## Status safety

| Bundle status | Persist by default | Decisions | Execution-ready |
| `completed` | yes | 0 | no; next is brief/verification review |
| `needs_human` | yes | 1..3 | no; next is human Decision |
| `partial` | yes | 0..3 if schema-consistent | no |
| `budget_exhausted` | yes | 0..3 if schema-consistent | no |
| `failed` | only with `--accept-failed` | 0 | no |
| `skipped` | yes | 0 | may recommend Direct, never mutate route |

Even `completed` does not approve a Work Brief, pass a Test, complete a
Feature, or satisfy deterministic verification.

## Work breakdown

| Task | PR boundary | Size | Depends on | Exit proof |
|---|---|---:|---|---|
| 0154 | ADR and proposal contract freeze; no runtime behavior | M | 0153b | Accepted/modified ADR, seven schemas/examples, conflict decision |
| 0155 | Runtime contract validators and built-in registry | L | 0154 | list/show/validate, package tests, no execution hooks |
| 0156 | Deterministic read-only request preparation | L | 0155 | byte-stable request and zero state mutation |
| 0157 | Bundle validator and dry-run planner | L | 0156 | invalid corpus, deterministic findings, zero mutation |
| 0158 | Atomic Evidence ingest and idempotency | L | 0157 | exact mutation counts, rollback/crash/replay tests |
| 0159 | Decision proposal selection and paid/network authorization | L | 0158 | human provenance, hash binding, conflict/replay tests |
| 0160 | Offline Council Profile fixture and distribution E2E | M | 0159 | source/wheel/sdist end-to-end path |
| 0161 | Two-repository dogfood and Skill/docs parity | L | 0160 | approved dogfood packets and no secret leakage |
| 0162 | 10..20 task evaluation and adoption gate | L | 0161 | frozen cohort, baseline comparison, human adoption decision |

Tasks 0154 through 0160 are serialized because they share contracts, CLI,
Evidence, validators, Decisions, and package fixtures. After 0157 freezes the
I/O boundary, a separately approved external-runner prototype may proceed in
parallel with 0158–0160. Tasks 0161 and 0162 remain sequential integration
gates.

## Verification matrix

Every implementation task runs targeted tests first, then:

```bash
ruff check .
pytest
PYTHONPATH=src python -m pcl --help
PYTHONPATH=src python -m pcl validate --root <fresh-fixture> --strict --json
```

Additional release-gate checks:

- Python 3.10, 3.11, 3.12, and 3.13 CI.
- Wheel and sdist member checks for all schemas and the built-in manifest.
- Clean-wheel E2E without repository source on `PYTHONPATH`.
- No runtime dependency delta in `pyproject.toml`.
- Snapshot compatibility for start/finish/resume/next/brief/route/evidence-set/
  completion surfaces.
- State/hash snapshots before and after every read-only or rejected operation.
- Crash points before staging, before rename, after rename/before commit, and
  during outbox projection.
- Case-fold collision and symlink tests on supported platforms.
- Candidate prepare and authorized re-prepare at different wall-clock times
  produce the same basis digest when semantic state is unchanged.
- Legacy `decision resolve/waive` rejects proposal-linked Decisions with zero
  mutation while remaining compatible for ordinary Decisions.
- Audit detects a finalized unreferenced Profile bundle directory left by a
  rename-before-commit crash.

## Risk register

| Risk | Trigger / detection | Mitigation | Rollback / escalation |
|---|---|---|---|
| Contract drift between Core and runner | Fixture or conformance mismatch | Freeze 0154 schemas; version every change; clean-package E2E | Reject unknown version; keep stored bundle readable |
| Partial filesystem/DB durability | Crash injection or audit orphan finding | Existing temp/rename/transaction/outbox pattern plus Profile-specific orphan detection | Roll back rows/files or use audit report/quarantine guidance; never guess human state |
| False confidence from model consensus | Claims lack deterministic/human Evidence | Typed claim classes and execution-ready guards | Persist as incomplete Evidence and route to verification/Decision |
| Secret or excessive repository disclosure | Secret sentinel or size/data-policy finding | Basis-bound authorization, deny-by-default paths, size caps | Abort before provider/ingest; revoke authorization and rotate exposed secret |
| Council overhead on clear work | Clear cohort gets Profile recommendation | Direct remains default; measure insertion and review cost | Keep experimental or reject adoption at 0162 |
| Event-only replay lookup becomes slow | Dogfood shows repeated scan/query cost | Measure before schema promotion | Separate human-approved indexing/table ADR |
| External runner quality/cost is misreported | Provider alias, cost estimate, schema failure | Requested vs reported model fields and honest uncertainty | Block adoption or constrain providers/topologies |

## Contract operations and maintenance

- Each supported contract version has one validator, schema, canonical example,
  negative corpus, and package-member test.
- Unknown versions fail closed with the supported-version list and no mutation.
- Additive or breaking shape changes after 0154 use a new version; stored
  artifacts are never rewritten in place.
- Deprecation requires at least one documented compatibility window and a
  clean-wheel test for the old reader before removal.
- `pcl profile show/validate` reports manifest source, hash, trust, supported
  contracts, and compatibility without invoking the runner.
- 0161 operator docs own credential isolation, authorization revocation,
  failure retry, and artifact retention guidance. 0162 owns the adoption
  decision, not ongoing hidden telemetry.

## Rollout and rollback

1. 0154–0160 ship as an experimental, built-in-only, opt-in Profile.
2. Direct behavior and route defaults remain unchanged.
3. A code rollback removes Profile CLI/runtime modules while retained Evidence
   stays readable as generic immutable artifacts and retained Decisions stay
   valid existing entities.
4. Contract changes after 0154 require a new contract version and fixture
   migration; they do not rewrite stored bundles.
5. No external runner repository, paid/API dogfood, publication, or default
   enablement occurs without a new explicit human approval.

## Separate Adoption/Distribution track

Council tasks 0154–0162 do not close the whole v0.5.0 release. README split,
contract stability policy, examples/quickstarts, `.project-loop` commit policy,
and publication readiness belong to a separately numbered release-readiness
track. It may run alongside late Council dogfood when paths do not overlap, but
both tracks must pass before a v0.5.0 publication decision. Council feature
completion must not be blocked by unplanned release-readiness work, and release
publication must not infer those items from Council DoD.

## Human gates

| Gate | Deadline / trigger | Required outcome |
|---|---|---|
| ADR-005 boundary | before 0155 starts | Human Accept/Modify/Reject record |
| Contract freeze | before 0155 runtime validators merge | All seven shapes and the old v0 supersession are explicit |
| External runner repository | after 0157, before production runner work | Owner, release cadence, data policy, and repository creation approval |
| Paid/network dogfood | before any real provider call in 0161 | Hash-bound human provenance naming allowed data and budget |
| Database migration | whenever a task cannot satisfy the plan on schema 8 | Stop; separate migration proposal and approval |
| Default recommendation | after 0162 results | Human adopt/adopt-with-constraints/continue/reject Decision |
| v0.5.0 publication | after Council and Adoption/Distribution tracks close | Separate human release decision with both evidence packets |

## Milestone Definition of Done

v0.5.0 Council Profile is complete only when:

1. The nine task acceptance packets are complete and independently reviewed.
2. All seven contract validators and canonical fixtures pass with no runtime
   dependency increase.
3. Read-only and invalid paths prove zero mutation.
4. Valid ingest is atomic, immutable, auditable, and idempotent.
5. `needs_human` opens existing Decisions and only hash-bound human provenance
   can select a candidate.
6. `partial`, `budget_exhausted`, and `failed` never become execution-ready.
7. Source, wheel, and sdist offline E2E tests pass.
8. Direct/start/finish/resume/next behavior remains compatible.
9. Two dogfood cases and one intentional failure/safe-stop case receive human
   review.
10. The 10..20 task evaluation is frozen before inspection and ends in an
    explicit human adoption Decision. Until then, Council remains experimental.
