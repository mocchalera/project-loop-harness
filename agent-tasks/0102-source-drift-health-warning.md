# 0102: Source drift must surface as evidence health warning

Milestone: v0.2.4 Trust Patch
Priority: P1
Area: evidence
Origin: docs/project-loop-harness-v0.2.3-third-party-review.md P1-1 (verified against main)

## Problem

`_collect_copied_member_findings` in `src/pcl/evidence.py` emits `source_drifted`
findings (detail `missing` or `size_mismatch`) when the original source of a
copied evidence member has drifted. But `source_drifted` is not in
`ADHOC_WARNING_FINDING_CODES` (evidence.py:36), so `_adhoc_assessment` returns
`health: "ok"` when the only findings are `source_drifted`. Agents and humans
read "ok" and miss the provenance/freshness problem.

## Scope

1. Add `"source_drifted"` to `ADHOC_WARNING_FINDING_CODES` in
   `src/pcl/evidence.py`.
2. Confirm the rendering path in `src/pcl/validators.py` (the
   `elif code == "source_drifted":` branch around line 977) stays consistent
   with the new classification — the finding text must keep re-rendering
   identically through the shared `assess_adhoc_evidence` path (0095 pattern).
3. Tests that pin the semantics:
   - copied artifact intact + source file deleted → `health: "warning"` with a
     `source_drifted` finding, `detail: "missing"`.
   - copied artifact intact + source size mismatch → `health: "warning"` with
     `detail: "size_mismatch"`.
   - copied artifact intact + source intact → `health: "ok"` (no regression).
   - copied artifact corrupted (`copy_hash_mismatch`) + source drifted →
     still `warning` (both findings present, no double-count crash).
4. `pcl validate --strict --json` must treat `source_drifted` as a warning that
   remains a warning under strict (extend the existing
   `_strict_warning_remains_warning` coverage), not an error, and must stay
   green overall.

## Invariants (what to protect, on the normal paths)

- The copied artifact stays usable: no finding may remove or rewrite copied
  files under `.project-loop/evidence/adhoc-files/`; assessment is read-only.
- The findings array shape is additive-only: existing finding codes, their
  `path`/`detail` fields, and their ordering semantics are unchanged.
- Health values remain the existing three-level `ok | warning | error`; do not
  introduce `artifact_health` / `source_health` split fields (explicitly
  deferred by approval 2026-07-08).

## Non-scope

- artifact_health / source_health separation (deferred until dogfood
  source_drift_rate data exists).
- Schema or migration changes.
- Context pack / dashboard surfacing changes beyond what the shared
  assessment already propagates.

## Acceptance

- All tests above green; full `pytest` green.
- Live smoke: create copied evidence in a scratch project, delete the source,
  run `pcl validate --strict --json` → evidence health shows `warning`,
  strict stays `ok: true`.
- Release note entry describing the semantic change.
