# 0114: Source hash drift detection for copied evidence

Milestone: v0.3.0 Target-Bound Context
Priority: P2
Area: evidence
Origin: docs/growth-plan-v0.2.4-v0.5.md 論点2; third-party review P1 / 議題2 —
default-on approved (坂本承認 2026-07-08). Extends 0102.

## Problem

`_collect_copied_member_findings` in `src/pcl/evidence.py` (the source-freshness
block at evidence.py:589-605) detects source drift only via `detail: "missing"`
and `detail: "size_mismatch"`. A **same-size content change** to the source
file is undetected: `source_drifted` never fires, so a copied evidence member
whose origin was silently rewritten to a different-but-equal-length body reads
as fresh. The recorded member `sha256` (`expected_sha256`) is already a
parameter of this function (evidence.py:545) but is never compared against the
current source.

0102 already classifies `source_drifted` as an evidence-health **warning**, so
closing this gap needs no health-model change — only the missing hash
comparison.

## Scope

1. In `_collect_copied_member_findings`, extend the `else` branch that currently
   only handles the size check: when the source exists **and**
   `source_stat.st_size == size_bytes`, compute the source file sha256 (reuse
   `_sha256_file`, evidence.py:907) and compare to `expected_sha256`.
   - Mismatch → append `{"code": "source_drifted", "path": member_path,
     "detail": "hash_mismatch"}`.
   - `OSError` while reading the source → treat as unreadable and reuse the
     existing `detail: "missing"` finding (do not crash, do not add a new code).
2. Default-on, no `--deep` flag. The hash is computed **only** in the same-size
   branch, so `missing` and `size_mismatch` stay the cheap fast paths. The
   `copy_max_member_bytes` cap (10MB, 0097) bounds per-member cost.
3. Confirm the `validators.py` `source_drifted` rendering branch (the
   `elif code == "source_drifted":` branch, ~line 977) renders the new
   `hash_mismatch` detail consistently through the shared
   `assess_adhoc_evidence` path (0095 pattern) — health stays `warning`.

## Invariants (what to protect, on the normal paths)

- Read-only assessment: no finding rewrites or removes copied artifacts under
  `.project-loop/evidence/adhoc-files/` or any source file.
- Findings shape is additive-only: `source_drifted` gains one new `detail`
  value, `hash_mismatch`. Existing `missing` / `size_mismatch` details, their
  `path` field, and ordering are unchanged.
- Copied-artifact health stays semantically **separate** from source freshness
  in wording (0102 invariant): `copy_hash_mismatch` = the copied artifact broke;
  `source_drifted/hash_mismatch` = the origin changed since the copy. Do not
  merge or cross-reference the two codes.
- Health stays the three-level `ok | warning | error`; no `artifact_health` /
  `source_health` split (still deferred until dogfood `source_drift_rate` data).

## Non-scope

- A `--deep` / lightweight-vs-deep mode split (unnecessary: the size gate plus
  the 10MB member cap already bound cost).
- Hashing sources of **reference** (non-copied) members — reference members are
  already hash-checked against the source directly by `_assess_reference_member`.
- `artifact_health` / `source_health` field separation.

## Acceptance

- Test: copied artifact intact + source rewritten to different content of the
  **same byte length** → `health: "warning"` with a `source_drifted` finding,
  `detail: "hash_mismatch"`.
- Test: copied artifact intact + source intact → `health: "ok"` (no regression).
- Test: `copy_hash_mismatch` (artifact corrupted) + `source_drifted/hash_mismatch`
  co-occur → still `warning`, both findings present, no double-count crash.
- `pcl validate --strict --json` treats `source_drifted/hash_mismatch` as a
  warning that remains a warning under strict (extend
  `_strict_warning_remains_warning` coverage) and stays green overall.
- Live smoke: in a scratch project, `evidence add --copy` a file, edit the
  source to same-length different content, `pcl validate --strict --json` →
  evidence health `warning`, detail `hash_mismatch`, strict `ok: true`.
- Full `pytest` green; release note entry describing the tightened semantics.
