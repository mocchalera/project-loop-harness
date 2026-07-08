# 0103: SECURITY.md v0.2.x update and copied-evidence policy

Milestone: v0.2.4 Trust Patch
Priority: P1
Area: docs/security
Origin: docs/project-loop-harness-v0.2.3-third-party-review.md P1-2 (verified: SECURITY.md still says `0.1.x` while the released line is 0.2.x)

## Problem

SECURITY.md states the current public release line is `0.1.x`, contradicting
the v0.2.3 release. Additionally, v0.2.3 introduced `pcl evidence add --copy`,
which retains copies of source files under
`.project-loop/evidence/adhoc-files/` — a new secret-retention surface that the
security policy does not mention.

## Scope

Update `SECURITY.md` only (no code changes):

1. Supported versions table: `0.2.x` = supported, `<0.2` = not supported.
2. Add a "Copied evidence" section stating:
   - `.project-loop/evidence/adhoc-files/` may contain copied sensitive source
     files when `--copy` is used.
   - Copied evidence must not be committed unless intentionally curated;
     `.project-loop/` is gitignored by default and should stay so.
   - Redaction is caller responsibility; `pcl` performs path-shape sensitive
     guards (0096) but is not a secret scanner (established v0.1.11 decision —
     keep this wording).
   - MCP / read-only exposure must not reveal raw evidence contents by
     default.
   - Dashboard HTML is a human view, not a machine context source.
3. Note that the release checklist (0106) will include a SECURITY.md
   supported-versions check per release.

## Invariants

- Do not weaken any existing statement in SECURITY.md; changes are additive or
  version-string corrections.
- Keep the established epistemic vocabulary (claims-not-facts; no "scanned /
  guaranteed secret-free" style assertions).

## Acceptance

- SECURITY.md shows `0.2.x` as the supported line.
- Copied evidence risks and commit policy are stated.
- `pytest` green (docs-only change; no test changes expected).
