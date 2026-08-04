# Architecture

## Definition

Project Loop Harness is a local agentic project control plane.

It is designed to let coding agents work through bounded loops while humans can inspect progress through a deterministic dashboard.

## System layers

```text
1. Human goal
2. pcl CLI / harness runtime
3. Workflow templates
4. Agent jobs and optional subagents
5. Evidence collection
6. Verification
7. SQLite state and JSONL audit log
8. HTML dashboard and markdown reports
9. Stop / retry / escalation decisions
```

## Key separation

| Layer | Responsibility | Must not do |
|---|---|---|
| Skill | Teach agent how to use the harness | Mutate state directly |
| CLI | Mutate state, validate, render, schedule, and package read-only context | Become model-specific |
| SQLite | Store current normalized state | Be hand-edited by agents |
| JSONL | Preserve audit trail | Serve as query engine |
| HTML | Human-readable view | Become source of truth or agent context |
| Plugin | Package Codex-facing assets | Replace CLI/runtime |
| MCP | External tool bridge | Own local state logic |

## Local project installation shape

```text
target-project/
├─ AGENTS.md
├─ CLAUDE.md
├─ pcl.yaml
├─ .agents/
│  └─ skills/
│     └─ project-control-loop/
│        └─ SKILL.md
└─ .project-loop/
   ├─ project.db
   ├─ events.jsonl
   ├─ goals/
   ├─ workflows/
   ├─ workflow-proposals/
   ├─ dashboard/
   ├─ evidence/
   ├─ exports/
   ├─ reports/
   ├─ tmp/
   ├─ cache/
   └─ worktrees/
```

## Control flow

```text
pcl loop run defect_repair --defect D-0001
  -> creates workflow_run
  -> creates agent_jobs
  -> generates prompts
  -> invokes configured agent runner or asks human to run the prompt
  -> ingests outputs and evidence
  -> runs verifier
  -> updates state through service layer
  -> validates
  -> renders dashboard
  -> stops, retries, or escalates
```

## Why SQLite + JSONL

SQLite is authoritative for current normalized state, ordered events, and
transactional JSONL delivery intent. JSONL is a derived, append-only,
rebuildable projection of committed SQLite events; it is not a source for
rebuilding arbitrary domain tables.

Do not choose only one:

- SQLite alone is hard to review with ordinary text tools.
- JSONL alone is awkward for query, joins, and validation.
- CSV alone is too easy to corrupt as the loop grows.

Every public mutation owns a `BEGIN IMMEDIATE` transaction containing its
domain writes, event row, and outbox row. After the authoritative commit, a
bounded synchronous projector writes canonical UTF-8 JSONL in event sequence,
calls `fsync`, and only then marks the outbox row delivered. Projection failure
does not undo committed domain state; retry with `pcl audit flush` rather than
re-running the mutation.

Direct Setup (`pcl start --direct-spec`) is an additive one-call bundle for a
Goal, Task, Feature, draft Stories, planned Tests, and the start receipt. It
securely fixes a project-local, single-link spec to one descriptor buffer and
retains the root directory device/inode capability through DB admission,
SQLite commit, projection, and the optional tail. Linux Git revision resolution
inherits the verified root descriptor; Darwin uses its stable file-ID path.
The DB, projector, and tail do not return to the original pathname, so root
rename/replacement cannot mix an old-root spec with a replacement-root
database. In particular, read-only SQLite URIs preserve the retained
file-ID/descriptor path without a second `resolve()` or `realpath()` step. It
then uses the existing project-operation lock exclusively and
performs schema-8/integrity/event/outbox/active-work admission in the same
`BEGIN IMMEDIATE` snapshot. A request-derived full-SHA-256 `work_started` event
primary key is the idempotency anchor; the event and Evidence carry the same
hash-bound receipt. The former 48-bit form is an exact-singleton, fully
verified legacy-retry read path only. No new schema or uniqueness table is
required.

After a successful Direct commit, validation and exact-target routing are
read-only and checked against one event high-watermark. Canonical rendering is
allowed only after acquiring the existing exclusive project-operation lock and
rechecking that watermark, then the current renderer is called at most once.
The private Direct lock-held call avoids re-entry and requires a live exclusive
capability bound to the same project root, loop directory, and open lock-file
identity. The capability is valid only for its issuing process/thread and live
registry entry; root/path ABA, lock-file replacement, forged/expired/reused
tokens, and a token from another root are rejected. Every public canonical
renderer caller uses the same exclusive lock-aware wrapper. The renderer
remains a derived two-file writer; this is not a claim of two-file or
process-crash atomic publication.

Atomic Task Accept (`pcl task accept`) is the terminal complement to Direct
Setup. It retains the same verified-root and exclusive operation capability,
publishes one immutable copied base Evidence through exclusive no-overwrite
storage, and performs all Test, Feature, Task, event, and outbox changes in one
schema-8 transaction. The full strict validator runs once against the exact
planned unprojected event suffix; its formal findings feed the existing P0-B
classifier without a second validator call. The Task update and its reserved
authority event/outbox are the exact post-strict three DML statements. Durable
request claims, Evidence reservations, and a single-head generation chain
separate exact replay, stale pre-commit successor attempts, accepted authority,
and post-commit tail recovery. See [task-accept.md](task-accept.md).
Committed authorities missing their post-commit acceptance marker are closed
only by `audit flush`: it verifies the receipt-bound current proof and records a
tail-recovery generation without replaying business DML.

Task Accept filesystem currentness is linearized at the successful final
retained-descriptor reseal, conditional on the staged SQLite transaction later
committing. This is intentionally not a cross-filesystem/SQLite atomicity
claim. Retained descriptors stay live through physical commit and are checked
again before post-commit authority publication. A detected post-linearization
change preserves the committed business state but isolates its tail with exit
6; later validation and recovery classify current copied-Evidence corruption
as an active integrity error and never overwrite or adopt the corrupt object.

Task completion adds a pre-update proof gate inside that same transaction.
The exact `routing-target/v1` Task is re-read and evaluated through the shared
`terminal-readiness/v1` collector before its row changes. The receipt binds the
current event high-watermark and a canonical digest of dependencies, linked
lifecycle entities, proof Evidence, Workflow/Goal state, formal findings, and
human gates. A failed gate rolls back before event/outbox insertion and never
reaches post-commit projection or rendering.

Task-bound finish uses the same receipt on both sides of its long-running
checks. Its final `BEGIN IMMEDIATE` re-resolves the exact Task and rejects a
changed status, HWM, input digest, or blocked proof before storing check
Evidence or writing a completion packet. This freshness gate is separate from
ordinary failed-check Evidence, whose existing incomplete-attempt semantics
remain authoritative.

P1-C C1 adds a read-only `authority-surface-resolution/v1` library contract.
It derives the risk-comparison base from an append-only Task-start revision or
an explicitly trusted integration-head merge-base, binds the canonical Git
diff and base/candidate/union catalog and canary hashes, and composes all risk
and verification inputs by maximum rank. Candidate configuration cannot delete
or weaken a trusted rule/canary. The external bootstrap profile forbids
self-certification and requires exact-candidate full regression plus fixed-hash
independent review. C1 adds no proof command, event, Evidence, terminal input,
render, schema, migration, dependency, or default enablement. See
[authority-surface-resolution-v1.md](authority-surface-resolution-v1.md).

P1-C C2 adds an internal, effect-zero proof workspace. It clones the exact
ref-reachable candidate into a fresh POSIX lease with distinct Git metadata,
seals every Git command and child environment, verifies the committed tree,
and materializes only declared typed external inputs. It produces a frozen
`PreparedCheck` and deterministic in-memory bindings, but executes no check and
authorizes no reuse. `verification-input-manifest/v1` remains an in-workspace
effect classifier rather than shared candidate identity. C3 must consume the
frozen spawn vector without reconstructing it; C4 owns mandated canary/role
coverage. See [proof-workspace-v1.md](proof-workspace-v1.md).

P1-C C3 adds an internal, effect-zero proof executor. It consumes C2's frozen
`PreparedCheck` directly, rechecks the canonical source/common object store and
C1 authority around every spawn, and uses one POSIX process group with bounded,
deadlock-free stdout/stderr draining. Canonical in-memory packets, checkpoints,
logs, receipts, results, and bundle manifests are deterministic and
hash-bound; `reuse_authorized` remains false. Feature-linked current proof is
captured in separate read-only SQLite snapshots, while a standalone Task is
explicitly not applicable. C3 persists or anchors nothing and adds no CLI,
schema migration, dependency, render, or lifecycle mutation. C4 still owns
semantic role/canary coverage. See
[proof-execution-v1.md](proof-execution-v1.md).

P1-C C4 adds a pure, in-memory semantic coverage admission join. A private
trusted-producer capability binds an exact full-regression/canary policy; C4
then joins distinct live C2/C3 proof chains only after checking their common
Task, candidate tree, C1 resolution, bootstrap profile, and canary union. It
resolves required candidate blobs through a sanitized direct `GitRunner`,
keeps raw execution ordering separate from sorted audit labels, and derives
current-proof match, per-role freshness, reasons, and admission state as total
permutation-invariant functions. Reviewability and promotion suitability are
facts only: independent/human authorization remains pending and anchor, reuse,
Evidence, persistence, CLI, terminal, and lifecycle integration remain C5 or
later work. SQLite stays schema 8 and C4 has no runtime writes or PCL effects.
See [proof-admission-v1.md](proof-admission-v1.md).

P1-C C5 adds the first durable proof-admission boundary. It recomputes live
C2/C3/C4 and authority inputs under the project mutation lock, requires
independent review and any policy-required human gate, and atomically binds an
immutable local artifact to one Evidence row, Task link, Task event, and outbox
record. Exact replay is effect-zero; unhealthy committed artifacts advance only
through a bounded, predecessor-bound recovery chain, followed by a durable
subject-independent exhaustion tombstone. C5 grants only
`anchor_authorization_granted`: C4's false reuse, terminal, mandatory-Evidence,
and anchoring facts remain embedded unchanged, and no C6 consumer is enabled.
SQLite remains schema 8 and C5 adds no migration, dependency, public CLI,
lifecycle mutation, render, network, or publication behavior. See
[proof-anchor-v1.md](proof-anchor-v1.md).

P1-C C6 adds only an internal, read-only local drift predicate over that C5
authority. It resolves the asserted anchor event first, gives invalid or
multiple exhaustion tombstones precedence, observes the existing project lock
without creating it, and holds one `mode=ro` / `query_only` schema-8 snapshot
while reconstructing the live C1-C4 basis. Its closed receipt always keeps
direct-input, check-skip, result-substitution, terminal, lifecycle,
mandatory-Evidence, promotion, publication, network, and telemetry rights
false. It writes no database, Evidence, event, outbox, filesystem authority,
or cache state and has no public CLI/MCP/renderer consumer. See
[proof-anchor-drift-v1.md](proof-anchor-drift-v1.md).

v0.6.0 adds an independent opt-in Mainline Progress Guard at the ordinary
continuation seams. It keys policy state by project instance, Goal, and logical
Exit Gate, reconstructs counters from schema-8 Events, and stops `next`,
`pcl start --goal` successor creation, and workflow Run/Job creation after the
configured consecutive-zero limit. Manual `pcl task create` and external
Cockpit task creation are not blocked. Task/Run/Route/environment aliases are
observation metadata rather than lineage identity. Operator replan is an
audited caller attestation, not cryptographic human authentication. This is
cooperative policy enforcement, not malicious-agent resistance or external
Cockpit containment.
See [mainline-progress-guard-v1.md](mainline-progress-guard-v1.md).

## Why CLI first

Agent Skills are instructions. They cannot reliably guarantee migrations, validation, deterministic rendering, or guarded state transitions by themselves.

The CLI is the runtime body. The Skill only tells agents how to use it.

## Guarded executor boundary

`pcl workflow guard` and `pcl loop execute` use an allowlisted host-subprocess
executor. The executor passes an argv list with `shell=False`, fixes the working
directory to the project root, and inherits only an explicit environment-variable
allowlist. It does not provide OS, network, or filesystem isolation. A future
container backend may implement stronger isolation behind an explicit backend
contract; the current host backend must never be presented as a sandbox.

`pcl finish --emit-packet` adds a narrower repository-safety layer around the
same host executor. It runs project checks in a temporary independent Git copy,
compares pre/post `verification-input-manifest/v1` artifacts, and rejects input
mutation as completion proof. This protects the canonical Git working tree from
ordinary check writes, but it is not an OS sandbox: absolute-path writes,
network access, and writes through external tools or environments remain
outside this guarantee.

Each stdout and stderr stream is drained incrementally and retains at most 1 MiB
by default. Evidence records the configured cap, original byte count, retained
byte count, head-retention strategy, timeout/termination status, and truncation
reason. Secret-shaped output is conservatively redacted before artifact storage;
raw output is not retained elsewhere. Redaction metadata is reviewable, but the
filter is not a secret scanner and does not prove that output is secret-free.

## Machine Context Packs

`pcl context pack` is a read-only packaging surface for focused agent handoffs.
It must not mutate SQLite, append events, write packs to disk, or parse
generated dashboard HTML.

That statement describes the default path. DEC-0004 adds an explicit
`--record-usage` opt-in: after a successful pack build, the CLI records exactly
one local `context_pack_generated` event through the normal mutation transaction
and outbox. The event is usage accounting only and does not affect pack selection
or content. If the mutation or projection cannot be completed, the command
returns the normal explicit datastore or projection-pending error. KPI reports
therefore cover only context packs generated with this opt-in flag.

Job packs and task packs share the additive `context-pack/v1` JSON contract.
Job packs include lease fields and rubric-aware verification columns. Task
packs include task dependencies, dependents, linked goal/feature/defect
context, sibling tasks, and recent events.

Role profiles affect which sections fit under a tight budget, but included
sections are always rendered in canonical document order. Budget selection uses
the deterministic `charclass/v1` estimator rather than parsing model-specific
tokenizers or slicing generated Markdown after rendering.

## Explainable Code Context

`pcl index build` creates an explicit local snapshot of code files with
gitignore-aware omissions, hashes for small text files, symbol-lite summaries,
and test hints. The index lives in schema version 4 tables and appends an event
for each build.

The index is not source of truth. The working tree and Git state remain
authoritative; `pcl index status` and `pcl impact` surface staleness warnings
when the snapshot differs.

`pcl impact --diff` writes a `context-receipt/v0` JSON artifact as normal
evidence. The receipt records `included_candidate_context`, `omitted`, and
`staleness_warnings` so later review can see what PLH provided and why.
