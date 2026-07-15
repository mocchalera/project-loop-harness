# Scale baseline and event-log policy

**Status:** Proposed baseline; documentation and fixture only
**Reference revision:** `67cb42190bcf99921b4fc7fed8a8d8ade9259ac1`
**Reference date:** 2026-07-15
**Scope:** establish measurable limits before demand justifies runtime changes

## Decision

Project Loop Harness keeps SQLite as the authoritative current-state and event
store. `events.jsonl` is an ordered, rebuildable projection and
`outbox_records` is the delivery ledger. This task records a scale baseline and
future retention policy; it does not add rotation, compaction, telemetry, a
schema migration, or a performance gate.

The first operator-visible response to growth is an advisory report and an
explicit design review. No process may silently delete, rewrite, or compact
events to stay below a threshold.

## Reference snapshot

The following values were measured from the repository checkout at the
reference revision. They are observations, not service-level objectives.

| Surface | Observed value | Measurement |
|---|---:|---|
| `events.jsonl` lines | 1,207 | `wc -l` |
| `events.jsonl` bytes | 628,896 (0.60 MiB) | `wc -c` |
| SQLite `events` rows | 1,207 | read-only `COUNT(*)` |
| SQLite `outbox_records` rows | 1,207 | read-only `COUNT(*)` |
| SQLite `events` sequence range | 1–1,207 | read-only `MIN/MAX(sequence)` |
| Goals / Features | 38 / 38 | read-only row counts |
| Stories / Tests | 36 / 101 | read-only row counts |
| Tasks / Evidence | 61 / 374 | read-only row counts |
| `dashboard-data.json` bytes | 156,713 (0.15 MiB) | `wc -c` |
| generated dashboard HTML bytes | 109,580 (0.10 MiB) | `wc -c` |
| `.project-loop` directory | 15 MiB | `du -sh` |
| `project.db` bytes | 3,579,904 (3.41 MiB) | `wc -c` |

The JSONL and SQLite counts agree in this snapshot. The fixture does not treat
that agreement as a permanent invariant for arbitrary historical projects;
`pcl audit check` remains the authority for projection health.

## Proposed advisory bands

These bands are planning triggers, not enforced limits or measured latency
claims. They are intentionally based on two independent dimensions: event
count and bytes. Crossing either boundary enters the higher band.

| Band | Event rows / JSONL lines | JSONL bytes | Whole `.project-loop` | Meaning |
|---|---:|---:|---:|---|
| S0 smoke | ≤1,000 | ≤5 MiB | ≤25 MiB | ordinary fixture and CLI contract checks |
| S1 maintainer | 1,001–10,000 | 5–25 MiB | 25–100 MiB | routine dogfood; collect timings and render size |
| S2 growth study | 10,001–100,000 | 25–250 MiB | 100 MiB–1 GiB | benchmark and design review only; no automatic policy |
| S3 review trigger | >100,000 | >250 MiB | >1 GiB | stop and approve a retention/compaction design before implementation |

The current snapshot is below S0 on file size and is retained as the
maintainer reference point. The bands must not be used to claim that a command
is fast, safe, or supported at that size until a benchmark run records the
command, machine, Python version, repository revision, and result.

## Benchmark fixture contract

`tests/fixtures/scale_baseline_v1/manifest.json` is the canonical, synthetic
fixture manifest. It contains no user paths, source text, timestamps, or random
IDs. The event mix is derived from the reference snapshot and the scale cases
use deterministic counts:

- `smoke-1k`: 1,000 event records;
- `maintainer-10k`: 10,000 event records;
- `growth-100k`: 100,000 event records.

Each case records its intended event count, payload multiplier, expected band,
and the commands a future benchmark runner must time. A runner must emit raw
timings and file sizes alongside the fixture revision; it must not overwrite
the committed manifest. The fixture is a workload description, not a request
to add a benchmark command to `pcl`.

Reproducibility requirements:

1. use the manifest's fixed event-type mix and canonical IDs;
2. generate into a temporary project, never this checkout's `.project-loop`;
3. record repository revision, Python version, platform, and command argv;
4. retain failed runs and distinguish tool failure from a low score;
5. report JSONL, SQLite, dashboard-data, and total loop bytes separately.

## Future rotation policy (design only)

Rotation is an explicit archival operation for the derived JSONL projection.
Before any future implementation is approved, it must:

1. flush pending outbox rows and run `pcl audit check`;
2. create a manifest containing before/after SHA-256 hashes, event count, and
   first/last event IDs and sequences;
3. preserve the complete pre-rotation JSONL backup and make the archive
   content-addressed or otherwise immutable;
4. atomically install the new active projection and leave SQLite untouched;
5. expose a dry-run, a recovery path, and an explicit human review receipt;
6. make replay and hash comparison prove that no event was dropped or
   reordered.

Automatic time-based rotation, background daemons, and silent file deletion
are out of scope. A threshold crossing should produce an advisory only.

## Future compaction policy (design only)

Compaction is more constrained than rotation. It may only rewrite a derived
projection after an approved policy version and a verified backup. It must not
delete SQLite events, outbox rows, Evidence records, or the audit history used
for lifecycle decisions. The compactor must preserve event identity and
sequence semantics, publish a before/after manifest, and support rebuilding
the active projection from SQLite.

Hash-chain or tamper-evidence guarantees remain a separate ADR decision. This
policy therefore uses the existing vocabulary: append-only, ordered,
rebuildable, and consistency-checked. It does not call the log tamper-evident.

## Non-goals and exit criteria

This baseline does not implement runtime rotation or compaction, add schema or
dependency changes, collect telemetry, change JSON/CLI contracts, or make
v0.5.1 Trace work start. The P2 item is complete when this document, the
fixture manifest, and a passing deterministic fixture-contract test are present
and the next implementation decision is explicitly left to a future approved
task.
