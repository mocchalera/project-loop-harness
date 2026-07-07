# Task 0095: Supporting Evidence Health in Verification Stats (v0.2.3, P0)

Origin: GPT-5.5-pro v0.2.2 review agenda, blind spot B ("feedback stats
do not look at the health of supporting evidence"). No migration, no
new runtime dependency; schema stays v5.

## Goal

`verification_feedback` rows can reference a `supporting_evidence_id`.
Since v0.2.2 that evidence is often an `adhoc_artifact` / `adhoc_bundle`
whose members are referenced (not copied) and hash-pinned. Stats can
therefore show a healthy `executed_pass_rate` while the artifacts
backing those feedbacks have since gone missing or drifted.

Add a **derived, read-only health axis** to `pcl verification stats
--json` that reports whether the supporting evidence behind executed
feedback is still reviewable today. Do NOT change any existing metric
and do NOT rewrite any feedback row: PLH records facts append-only;
health is a separate, current-time observation about reviewability.

## Vocabulary (binding)

- Health values: `ok` | `warning` | `error` | `unknown`.
- Health describes "current reviewability of the referenced
  artifacts". It never asserts the original claim was true or false.
- Forbidden in new output, help text, and docs for this feature:
  "verified", "proven", "guaranteed", "invalid(ated)". A drifted
  artifact does not invalidate a past feedback; it makes it harder to
  review now.

## Scope

### 1. Shared adhoc health assessment

Extract the adhoc manifest/member checks that already exist in
`src/pcl/validators.py` (`_validate_adhoc_evidence_manifests` /
`_validate_adhoc_members`) into a shared, structured assessment
function in `src/pcl/evidence.py`, e.g.:

```python
def assess_adhoc_evidence(paths, *, evidence_id, evidence_type, manifest_path_value) -> dict
# -> {"health": "ok"|"warning"|"error", "findings": [{"code": ..., "path": ...?, "detail": ...?}]}
```

Structured finding codes (at minimum): `manifest_not_local`,
`manifest_missing`, `manifest_not_file`, `manifest_corrupt`,
`contract_version_unsupported`, `evidence_id_mismatch`,
`evidence_type_mismatch`, `members_invalid`, `member_entry_invalid`,
`member_missing`, `member_hash_mismatch`.

Severity mapping mirrors today's validator semantics exactly:
structural manifest problems are `error`; member drift (missing file
or hash mismatch) is `warning`; everything intact is `ok`.

`validators.py` must consume this shared function so drift semantics
have a single source. Protective invariant, scoped: **the rendered
`pcl validate` / `pcl validate --strict` messages for the existing
test fixtures must remain unchanged — all existing validator tests
pass unmodified.** If message-identical rendering from structured
findings proves impossible for some edge case, stop and report
instead of changing a message.

The assessment must tolerate (ignore) unknown extra keys on manifest
members — task 0096 will add fields such as `path_scope` later.

### 2. `supporting_evidence_health` in stats

In `verification_feedback_stats` (`src/pcl/verification_feedback.py`),
assess every **distinct** `supporting_evidence_id` referenced by
feedback rows already loaded for stats (all statuses, not just
executed — a `skipped` feedback can also carry evidence):

- Evidence row absent in `evidence` table → `error` with finding
  `evidence_row_missing`. (Normally impossible — record-time checks
  existence — but deletion/corruption must surface, not crash.)
- Evidence row present, `type` in (`adhoc_artifact`, `adhoc_bundle`)
  → result of the shared assessment.
- Evidence row present, any other type (`context_receipt`, ingested
  agent output, test evidence, ...) → `unknown` with finding
  `health_not_assessed_for_type`. v0 assesses adhoc only; do not
  invent checks for other types.

Each distinct evidence id is assessed (and its member files hashed)
at most once per stats invocation.

New sibling section in the returned `stats` object (additive only —
no existing key changes, no metric formula changes):

```json
"supporting_evidence_health": {
  "assessed_evidence_count": 2,
  "feedback_events_with_supporting_evidence_count": 3,
  "health_counts": {"ok": 1, "warning": 0, "error": 0, "unknown": 1},
  "by_evidence_id": {
    "E-0018": {"health": "ok", "findings": []},
    "E-0017": {"health": "unknown",
               "findings": [{"code": "health_not_assessed_for_type",
                              "detail": "context_receipt"}]}
  }
}
```

Additionally, each entry in the existing
`latest_feedback_by_suggestion` map gains a
`supporting_evidence_health` key: the health string when that
feedback row has a `supporting_evidence_id`, else `null`.

### 3. Read surfaces and docs

- `pcl verification stats --json` carries the new section (it already
  prints the stats dict; no new flag).
- Docs: extend `docs/verification-feedback.md` with a
  "Supporting evidence health" section covering the four health
  values, the adhoc-only v0 scope, and the binding vocabulary rule
  (health ≠ truth; feedback rows are never rewritten).

## Non-goals

- No change to `pcl validate` behavior or output (refactor only).
- No dashboard/report rendering of health (v0.2.4 UX round).
- No health for non-adhoc evidence types beyond `unknown`.
- No caching of hash checks across invocations.
- No new events, no DB writes: stats stays a pure read. Protective
  invariant, scoped: **a `pcl verification stats` invocation must not
  append to `events.jsonl` nor change any table row** (assert in a
  test via row counts / file size before and after).

## Tests

1. Feedback with adhoc supporting evidence, members intact → `ok`;
   health appears in `by_evidence_id` and in
   `latest_feedback_by_suggestion`.
2. Overwrite one member file after recording → `warning` with
   `member_hash_mismatch`; delete a member → `warning` with
   `member_missing`. Existing metrics (`executed_pass_rate` etc.)
   unchanged by drift.
3. Delete the manifest file → `error` with `manifest_missing`.
4. Supporting evidence of a non-adhoc type → `unknown`.
5. Feedback without `supporting_evidence_id` → excluded from
   `health_counts`; `supporting_evidence_health: null` in
   `latest_feedback_by_suggestion`.
6. Same evidence id referenced by two feedback rows → assessed once,
   counted once in `health_counts`.
7. Stats invocation performs no writes (events.jsonl byte size and
   evidence/feedback row counts identical before/after).
8. All existing validator and stats tests pass unmodified.

## Definition of done

- Implementation + tests green (`python3 -m pytest`).
- Live smoke against this repo's own `.project-loop` (it already has
  VF-0001/VF-0002 and E-0017/E-0018 from dogfood): stats shows
  `ok` for E-0018 (adhoc) and `unknown` for E-0017 (context_receipt);
  then temporarily drift a member copy in a scratch project (not the
  live DB) to show `warning`.
- Docs updated. Evidence paths for all claims.
