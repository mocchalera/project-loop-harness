# 0201: gap-report/v1 Integrity Hardening

- **Status:** Complete
- **Milestone:** Harness Engineering Feedback Loop
- **Priority:** P1
- **Size:** M
- **Dependency:** 0200 Gap Report contract and Evidence flow
- **Project Loop:** Goal `G-0059`, Task `T-0123`, Feature `F-0065`, Story `US-0063`, Test `TC-0136`
- **DB schema:** remains 8

## Goal

Close the four integrity gaps found by the independent implementation review
without expanding the Gap Report feature or changing completion semantics.

## Corrections

1. Create the artifact directory, temporary file, and final file through
   canonical no-follow handles. Reject pre-existing directory, temporary-file,
   or final-file symlinks without writing outside the project or mutating PLH
   state.
2. Make Schema and runtime validation agree on real UTC calendar timestamps.
   Represent candidate lessons as an object keyed by `lesson_id`, and reject
   duplicate raw JSON keys at load time so uniqueness is structural.
3. Bind `artifact_sha256` to the exact stored bytes. Whitespace-only,
   same-length changes must make the report unhealthy.
4. Filter lists using the immutable class in the anchor event. Return both
   `recorded_gap_class` and `artifact_gap_class`, and do not silently hide
   records whose anchor class is invalid.

## Acceptance

1. Redirected artifact directory/temp/final paths fail with zero Evidence,
   event, outbox, or link mutations and leave the external target unchanged.
2. The packaged timestamp pattern and hand validator accept valid leap dates
   and reject invalid dates and year zero; duplicate lesson keys fail loading.
3. Same-size semantic-preserving byte drift produces
   `artifact_hash_mismatch`.
4. Artifact class tampering remains listed only under the recorded class and
   exposes both recorded and artifact values.
5. Targeted tests, full pytest, Ruff, source/wheel/sdist smoke, strict PLH
   validation, audit check, and render complete with results recorded as
   Evidence.
