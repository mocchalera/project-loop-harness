# Task 0093: `pcl evidence add` + Adhoc Bundles (v0.2.2, F2/F6)

Design source: `docs/evidence-entry-paths-design.md`
(**APPROVED 2026-07-07**, Parts 1-2 and the approval record). Where
this spec and the design doc disagree, the design doc wins. No
migration, no new runtime dependency; schema stays v5.

## Goal

Operators and agents produce reviewable artifacts outside the job
loop (test output, screenshots, visual-check reports) and PLH has no
honest way to accept them as evidence. Add the missing primitive.

## Scope

### 1. `pcl evidence add`

```bash
pcl evidence add --file work/reports/pytest-out.txt \
  --summary "pytest run for suggestion E-0017/VS-01" \
  --command "python3 -m pytest tests/test_context.py" --json
```

- `--file` is required and repeatable; every path must exist and be
  readable at record time (missing/unreadable → typed error, nothing
  recorded). `--summary` required. `--command` optional — it is the
  CALLER'S claim of how the artifact was produced; PLH stores it
  verbatim and never runs or verifies it (docs and help must say
  this).
- One file → evidence `type = 'adhoc_artifact'` (approved). Two or
  more files → `type = 'adhoc_bundle'` (approved).
- In both cases PLH writes a small manifest JSON under
  `.project-loop/evidence/adhoc/` recording, per member: relative
  path, size_bytes, sha256 — pinned AT RECORD TIME. Members are
  referenced in place, NOT copied (approved; a `--copy` mode is a
  possible later addition, do not add it now).
- The evidence row's `path` points at the manifest; `command` and
  `summary` come from the flags. One evidence row per invocation, one
  standard event via `append_event` (SQLite + JSONL both — never a
  side-channel writer; see agent-tasks/0089 clarification).
- Manifest contract name: `adhoc-evidence/v0` with a
  `contract_version` field. Deterministic member ordering (input
  order preserved; duplicates by path → typed error).
- JSON output returns the evidence id, type, manifest path, and the
  member list with hashes.

### 2. Strict validation integration

- `pcl validate --strict` verifies for adhoc evidence rows that the
  manifest file exists and parses; missing/corrupt manifest is an
  ERROR (state integrity).
- Member hash drift (file changed or deleted since recording) is a
  WARNING, not an error (approved): drift is the working tree moving
  on; the pinned hash remains the recorded claim. Warning text must
  name the evidence id, member path, and which aspect drifted
  (missing vs hash mismatch).

### 3. Documentation

- New section in `docs/data-model.md` or `docs/golden-path.md`:
  the adhoc evidence flow, the claim/pointer epistemic boundary, and
  the worked example ending in
  `pcl verification feedback ... --evidence E-00xx`.
- `docs/evidence-entry-paths-design.md` stays the design record; do
  not duplicate it wholesale.

## Acceptance Criteria

- Single file → `adhoc_artifact`; multiple files → `adhoc_bundle`;
  manifest carries per-member path/size/sha256; JSON output matches.
- Determinism: same files, same flags → identical manifest content
  except created_at/evidence id.
- Missing file, unreadable file, duplicate path → distinct typed
  errors, no evidence row, no event, no manifest file left behind.
- `validate --strict`: green after add; deleting a member → WARNING
  (still ok); editing a member → WARNING naming the hash mismatch;
  deleting the MANIFEST → ERROR.
- End-to-end test: `evidence add` → `verification feedback
  --status executed --evidence <new id>` succeeds (closes the M2
  dogfood gap).
- Events mirrored in SQLite and JSONL; strict audit integrity stays
  green (regression test).
- `ruff check .` passes; full `python3 -m pytest` passes; `pcl init`
  smoke against a temp dir passes.

## Do Not

- Do not copy member files or add `--copy` yet.
- Do not execute `--command` or capture output (`--capture` is out of
  scope by design).
- Do not add an M:N evidence link table or any migration.
- Do not use "verified"/"safe" language for adhoc evidence — it is a
  recorded claim with pinned hashes.
- Do not touch `verification feedback` flags (`--output-file` is
  formally superseded, not implemented).
