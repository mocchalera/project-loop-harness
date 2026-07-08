# Task 0101: Evidence ID Allocation Race (defect, P1)

Origin: observed in the field during the M0 dogfood (2026-07-08).
A worker ingesting three agent outputs in parallel hit
`UNIQUE constraint failed: evidence.id` on `J-0001`'s ingestion;
retrying sequentially succeeded (allocated E-0030). The failure is
in prefixed-ID allocation (`next_prefixed_id`): two connections read
the same max id before either inserts, then both try to insert the
same `E-XXXX`.

This affects every entity that allocates through the same helper,
not just evidence — audit the call sites (`src/pcl/ids.py` and
callers) and state in the fix which entities were exposed.

## Scope

1. Make prefixed-ID allocation safe under concurrent writers. Two
   acceptable shapes — implementer picks one and justifies it in the
   task output:
   - allocate inside an immediate/exclusive transaction so the
     read-max and insert are atomic, or
   - catch the UNIQUE failure and retry allocation a bounded number
     of times.
2. Whatever the shape, a failed attempt must leave zero traces
   (no orphan manifest/copy artifacts, no partial events) —
   the 0093/0096/0099 atomicity rule extends to retries. For copy
   mode (0099) note the ordering hazard: copies land under a
   directory named for the candidate evidence id *before* the DB row
   is inserted, so an id retry must re-stage or rename the copy
   directory, never leave one behind under the losing id.
3. Add a concurrency regression test (multiprocessing or threads +
   separate connections) that reliably reproduced the race before
   the fix and passes after.
4. Document the concurrency guarantee (or its limits) in
   `docs/data-model.md`.

## Out of scope

- Switching to UUIDs or changing the human-readable ID format.
- A general write-lock/daemon architecture.

## Definition of done

- The regression test fails on pre-fix code and passes post-fix.
- Parallel `pcl evidence add --copy` invocations (the M0 failure
  shape) succeed with distinct IDs and intact copies.
- `pytest` passes; `pcl validate --strict --json` passes; `pcl init`
  smoke-tested against `/tmp/pcl-demo`.
- Evidence paths recorded for all verification claims.
