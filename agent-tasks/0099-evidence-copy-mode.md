# Task 0099: Evidence `--copy` Mode (v0.2.4, P1)

Origin: approved design `docs/evidence-durability-design.md`
(task 0097; all six decision points approved as recommended on
2026-07-08). Demand signal: the master-trace context handoff plan
needs transcripts (typically short-lived files under `.work/` or
scratch directories) to survive workspace cleanup so a worker agent
can read them later.

Implements the design as specified. Where this file and the design
doc disagree, the design doc wins.

## Scope

Add opt-in `--copy` to `pcl evidence add`.

1. **Copy semantics.** After all 0096 guards pass, copy each member
   to `.project-loop/evidence/adhoc-files/<evidence-id>/<NN>-<basename>`
   (`NN` = two-digit member index). Stage copies in a temp directory;
   move into place only after every member succeeds and before the DB
   row/event are written. Re-hash each copy; a mismatch with the
   source hash is a typed error with zero traces (same atomicity rule
   as 0093/0096).
2. **Manifest accounting.** Member-level `storage_mode: "copied"` and
   `stored_path`. One mode per invocation — no mixed bundles.
   Reference-mode members omit both fields; pre-existing manifests
   stay valid (additive rule from 0096).
3. **Drift semantics.** Copied members: health checks hash the copy
   only. Missing/drifted copy → `warning` with new finding codes
   `copy_missing` / `copy_hash_mismatch`. Original drifting →
   informational finding `source_drifted`, no warning.
4. **Guards compose.** Sensitive-shaped member + `--copy` still
   requires `--allow-sensitive-evidence`; the copy inherits
   `sensitive_pattern` and the combined warning text states that
   copying amplifies exposure. Outside-root member + `--copy` keeps
   `path_scope: outside_project` with the original path in the
   manifest while `stored_path` holds the local copy.
   `evidence.allow_outside_root: false` still blocks recording
   entirely — configuration wins over copy.
5. **Size discipline.** New config `evidence.copy_max_member_bytes`,
   default 10 MB. Over cap → typed error
   `evidence_copy_member_too_large` (zero traces). Over half cap →
   `large_evidence_member` warning. Reference mode is untouched by
   the cap.
6. **Truthfulness wording.** `--help` and docs assert only: "at
   record time, PLH wrote a byte-identical copy (same sha256) of the
   file the caller named, to `stored_path`". "Durable" is always
   scoped as "survives workspace cleanup on this machine".

## Out of scope

- `pcl evidence export` transfer bundles (future task; design doc
  gitignore boundary option (c)).
- Any change to the gitignore status of `.project-loop/evidence/`
  (option (a) approved: local-only).
- Default-copy behavior. Copying stays opt-in per invocation.
- LLM calls, network access, new dependencies.

## Definition of done

- `pcl evidence add --copy` behaves as specified, including guard
  composition, atomicity, and typed errors.
- Health stats (0095) treat copied members as specified without
  changing the "each evidence id hashed once per stats invocation"
  cost model.
- Tests cover: happy path single/multi member, staging atomicity on
  mid-copy failure, hash-mismatch abort, sensitive × copy,
  outside-root × copy, over-cap error, half-cap warning, drift
  findings for copy vs original, manifest backward compatibility.
- `docs/context-pack.md` untouched; `docs/evidence-durability-design.md`
  status updated only if implementation deviates (it should not).
- Update `docs/data-model.md` and command help where manifest fields
  and config keys are user-visible.
- `pytest` passes; `pcl validate --strict --json` passes;
  `pcl init` smoke-tested against `/tmp/pcl-demo`.
- Evidence paths recorded for all verification claims.
