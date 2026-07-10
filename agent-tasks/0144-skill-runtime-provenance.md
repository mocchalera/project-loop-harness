# 0144: Skill/runtime execution provenance

- **Status:** Approved implementation slice
- **Milestone:** v0.4.1 Integrity Migration
- **Priority:** P1
- **Estimated size:** L
- **Dependencies:** 0142–0143 repair route merged; 0140a Skill/CLI parity; 0140b schema-8 target Evidence
- **Parallel-safe with:** not 0145; both change report surfaces and should merge serially
- **DB schema:** remains 8

## Problem

The harness can record repository revision and completion Evidence but cannot
prove which on-disk Skill instructions an agent used. A Skill path or name
alone is mutable, and Skills do not have a required version field. After a
dogfood run, reviewers therefore cannot distinguish the exact instruction
content from a later edit at the same path.

## Goal

Allow `pcl start` to hash explicitly supplied Skill files before mutation and
write a canonical `execution-provenance/v1` JSON artifact registered as
schema-8 target-bound Evidence. Anchor the artifact hash in the audit event,
then expose verified provenance and later Skill drift through machine-readable
inspection, reports, and the human dashboard without changing
completion-packet/v1.

## CLI contract

```text
pcl start "聴く仕事ラボLP" \
  --skill /absolute/path/mockup-to-code/SKILL.md \
  --skill /absolute/path/project-control-loop/SKILL.md
```

- `--skill` is repeatable and opt-in. Existing calls without it are unchanged.
- Each supplied path is normalized to an absolute display path, must identify a
  readable regular file, and is hashed as raw bytes with SHA-256 before any
  initialization or state mutation.
- Duplicate normalized paths are a typed input error rather than duplicate
  provenance entries.
- `pcl start --dry-run` performs the same read-only validation/hash step and
  returns the planned provenance entries without creating Evidence or files.
- An unreadable, missing, directory, or changed-during-read Skill fails before
  Goal, Task, Evidence, event, or initialization mutation.

## Schema 8 storage contract

No migration or new column is used. The start path writes canonical UTF-8 JSON
with sorted keys and one trailing newline to:

```text
.project-loop/evidence/execution-provenance/<evidence-id>.json
```

The artifact has this payload:

```json
{
  "contract_version": "execution-provenance/v1",
  "producer": {"name": "project-loop-harness", "version": "0.4.x"},
  "skills": [
    {
      "name": "mockup-to-code",
      "path": "/absolute/path/mockup-to-code/SKILL.md",
      "path_scope": "outside_project",
      "sha256": "64-lowercase-hex"
    }
  ],
  "repository_revision": "full-git-sha-or-null",
  "target": {"type": "task", "id": "T-0001"}
}
```

- Skill order follows CLI order and is deterministic.
- `name` comes from valid Skill metadata when available, otherwise the Skill
  directory name; no version is inferred from a name or path.
- `path_scope` is `inside_project` or `outside_project` after path
  normalization. Content is not copied into the project by this command.
- Register one existing-schema Evidence row with `type: execution_provenance`
  and `path` set to the project-relative canonical artifact path above. Its
  summary is factual and contains no absolute Skill path.
- Link the Evidence to the created Task with role `execution_provenance` using
  the existing schema-8 `evidence_links` table.
- Compute SHA-256 over the exact canonical artifact bytes. The `work_started`
  event payload stores `execution_provenance.evidence_id`,
  `execution_provenance.artifact_sha256`, `contract_version`, and target. The
  event's `artifact_sha256` is the immutable anchor; the Evidence row has no new
  hash column.
- Write and verify a same-directory temporary artifact, then use atomic rename
  and the existing Evidence transaction pattern for its Evidence/link/event
  references. A failed Evidence transaction cleans up the unreferenced artifact
  and leaves no provenance Evidence, link, event, outbox, or JSONL trace.
- The JSON start response includes the provenance Evidence ID and artifact
  SHA-256. Existing start-receipt/v1 fields remain additive-compatible.

## Inspection, drift, and presentation contract

- Inspection verifies in a fixed trust order: (1) read the immutable
  `artifact_sha256` from the matching event payload; (2) resolve the schema-8
  Evidence row and require `type: execution_provenance`, then hash the canonical
  artifact at its registered path; (3) only after the artifact hash matches,
  parse it and re-hash each current Skill path.
- An absent anchor/event, wrong Evidence type/path, missing artifact, or
  artifact hash mismatch reports provenance artifact failure and does not trust
  or follow Skill paths from the unverified artifact.
- After artifact verification, inspection reports per Skill
  `health: ok|drifted|missing|unreadable`, recorded/current SHA-256, and a
  factual reason.
- Drift is historical information: it does not rewrite the receipt or imply
  that the prior execution used the new bytes.
- Reports and dashboard data show Skill name, path scope, abbreviated recorded
  SHA, and health. Human HTML may render those fields but is never the machine
  source of truth.
- Absolute Skill paths exist only inside the verified canonical artifact and
  explicit provenance-inspection JSON. Evidence summaries, Markdown reports,
  dashboard data/HTML, finish summaries, and ordinary text output never embed
  absolute Skill paths.
- `pcl finish` discovers and reports the Task's provenance Evidence when
  present. It does not embed new fields in completion-packet/v1.

## Scope

- Extend `src/pcl/start.py` and its CLI parser/formatting.
- Add provenance record and assessment helpers in `src/pcl/evidence.py` and
  `src/pcl/evidence_show.py`.
- Surface provenance through `src/pcl/finish_execution.py`,
  `src/pcl/reports.py`, renderer data/HTML, and relevant exports where Evidence
  links already appear.
- Add start, evidence-show, finish, report, renderer, and distribution
  regressions.

## Invariants

- Existing `pcl start` idempotency and literal-intent handling remain intact.
- Skill paths are data, never shell commands, import targets, or executable
  hooks. No Skill code is launched.
- Hashing and dry-run are read-only. Invalid Skill input causes zero mutation.
- Canonical artifacts and their event hash anchors are immutable; later drift
  changes only derived health output.
- Missing provenance remains allowed for legacy starts and is reported as
  unavailable, not fabricated.
- `completion-packet/v1` has `additionalProperties: false`; this task neither
  edits that contract nor smuggles provenance fields into it. A packet change
  requires a separately designed v2.
- Storage is fixed to existing schema 8 Evidence + `evidence_links` + event
  payload fields. No schema migration, dependency, telemetry, network access,
  or automatic agent execution.

## Non-goals

- Discovering all Skills automatically from agent logs or global config.
- Assigning trust, authorship, signatures, or semantic version meaning to a
  content hash.
- Vendoring outside-project Skill content or publishing a Skill registry.
- Making Skill drift a terminal lifecycle failure in v0.4.1.

## Acceptance criteria

- Starting with two Skill paths creates one immutable provenance Evidence item
  of type `execution_provenance`, one canonical artifact at the fixed evidence
  directory, a Task link, and an event `artifact_sha256` anchor.
- Dry-run returns the planned hashes and leaves project/init/state files
  unchanged.
- Invalid or duplicate paths and a file changed during hashing fail with typed
  errors and zero mutation.
- Artifact write/verification or provenance Evidence transaction failure leaves
  neither an orphan provenance artifact nor partial provenance DB/event state.
- Re-reading unchanged Skills reports `ok`; byte changes, removal, and unreadable
  files report the corresponding health without changing stored Evidence.
- Artifact-byte tampering is detected against the event anchor before any
  embedded Skill path is followed; wrong Evidence type/path and missing
  event/artifact cases fail closed with factual health.
- Reports/dashboard data show Skill names and abbreviated recorded hashes, and
  explicit provenance inspection retains the full verified payload. No
  Evidence summary, report, dashboard, finish summary, or ordinary text output
  contains an absolute Skill path.
- Legacy starts without `--skill` keep their current JSON/behavior except for
  additive nullable provenance presentation.
- completion-packet/v1 fixtures remain byte-for-byte contract compatible.
- Targeted tests, full `pytest`, `ruff check .`, build/fresh-wheel smoke, strict
  validation, and render pass.

## Evidence required to close

- Canonical provenance artifact bytes/hash, schema-8 Evidence row, target link,
  and matching event `artifact_sha256`.
- Before/after Skill hash drift transcript.
- Event-anchor → artifact → current-Skill verification-order tests, including
  an artifact tamper case that proves embedded paths are not followed.
- Zero-mutation dry-run and invalid-path evidence.
- Completion-packet contract and fresh-wheel CLI regression output.
