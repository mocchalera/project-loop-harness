# 0161–0162 Claude Fable milestone review

Date: 2026-07-12

Verdict: **APPROVE**

Claude Fable independently reviewed commits `9056f1c`, `f3b6df9`, `ffb75c0`,
and `f35ee3c`, plus Evidence `E-0187` and `E-0190` through `E-0195`.

## Confirmed

- Governed human-only authorization revocation is idempotent and provenance
  bound; prior required finding R1 is closed.
- Bundle audit is anchored to the immutable ingest event and detects unlisted
  stored files; prior optional findings O1–O3 are closed.
- The real-repository dogfood used the production prepare, validate, and ingest
  path; Direct control failed closed without an invented override.
- Secret/privacy constraints, zero network/provider/cost claims, four Skill
  copy parity, and parser-valid examples hold.
- Finish dry-run did not mutate state and resume retained Council Evidence
  references.
- Cohort commit/Evidence preceded results commit/Evidence, its hash matched,
  all 12 cases and five categories were present, and reported percentiles and
  safe-stop arithmetic were internally consistent.
- Unavailable model quality, human-attention comparison, provider cost, and
  provider latency were left unavailable rather than fabricated.
- Direct remains default and the human adoption gate remains open.

Targeted reviewer run: 77 tests passed. Required findings: none.

## Optional next-cohort hygiene

The initial result file labels `CEC-01` as a safe stop although the aggregate
eligible list excludes it, and combines Direct route guards with status-level
safe stops. The math remains correct, but the next cohort should report route
guard and bundle-status safe stops as separate metrics. The frozen Evidence is
not rewritten to retroactively clean this label.

The reviewer also recommended enforcing the cohort hash pin in CI. That
assertion was added after review without modifying the frozen cohort or result
artifacts.
