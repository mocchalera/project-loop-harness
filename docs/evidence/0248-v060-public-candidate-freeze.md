# 0248 v0.6.0 public candidate freeze for the adoption proof

**Recorded:** 2026-08-23

**Worktree:** `evidence/issue2-adoption-readiness`

**Source milestone:** `da59b068f27becdc6a8bc857709f899787326638` (`origin/main`,
identical to tag `v0.6.0`)

## Outcome boundary

This record freezes the identity of one exact public artifact as the single
candidate for all five external adoption observations required by Issue #2. It
claims no participant outcome, no adoption result, and no release action.
External participant outcomes remain uncollected.

## Frozen candidate

| Field | Value |
| --- | --- |
| Project | `project-loop-harness` |
| Version | `0.6.0` (current latest public release) |
| Artifact | `project_loop_harness-0.6.0-py3-none-any.whl` |
| Size | 879348 bytes |
| SHA-256 | `4857355d108f720feb93497dc17ae53bb9b7502f4549a0f26c1a97cfa655137d` |
| Proposed candidate ID | `v0.6.0-pypi` |
| PyPI upload time | 2026-08-12T06:23:55 |
| Wheel URL | `https://files.pythonhosted.org/packages/72/57/74c41e09e8c3c6c223cef2452dc848969ba8b7dfcc192ab0766a2e9f8029/project_loop_harness-0.6.0-py3-none-any.whl` |

All five `adoption-observation/v1` records must use
`candidate_id: "v0.6.0-pypi"` and the SHA-256 above. If any future observation
uses a different artifact, the cohort identity gate fails by design and the
candidate must be refrozen under a new ID before recruitment restarts.

## Independent verification performed

1. **Registry metadata:** the PyPI JSON API
   (`https://pypi.org/pypi/project-loop-harness/json`) reports `0.6.0` as the
   latest version and lists the wheel digest above.
2. **Artifact bytes:** the wheel was downloaded from the PyPI CDN URL above and
   hashed locally with `shasum -a 256`; the result equals the registry digest
   byte-for-byte. These are two corroborating checks within the same PyPI
   distribution system, not independent sources.
3. **Installability smoke:** the downloaded wheel installed into a fresh
   Python 3.13 virtual environment; `pcl --version` printed `pcl 0.6.0`.
4. **Participant-path smoke:** in an empty scratch directory, `pcl init
   --dry-run --json` proposed writes without executing project code, `pcl init`
   succeeded, and `pcl doctor --strict` correctly reported placeholder and
   empty-command findings until real checks are configured. This confirms the
   healthy-setup definition is meaningful: it requires real configured checks,
   which is why eligible repositories must have obvious lint/test commands.
5. **Tag correspondence:** tag `v0.6.0` resolves to the same commit as
   `origin/main` at audit time (`da59b06`), and the wheel METADATA reports
   `Version: 0.6.0`.

No network access is required to evaluate records later; this freeze step used
the network once, up front, and its outputs are pinned here.

## Relationship to other evidence

- This resolution was performed independently of local release-preparation
  claims; `docs/evidence/0247-v060-release-preparation.md` records no wheel
  digest, so this document is the first durable in-repo freeze of the public
  candidate identity.
- The frozen protocol in `docs/adoption-proof-v0.5.2.md` and its participant
  kit are unchanged. Thresholds, schema, and evaluator behavior are untouched.

## Boundaries and residual risk

- Recruitment, sending invitations, and observing sessions remain human actions
  that have not occurred.
- The SHA-256 pins bytes, not intent: if the maintainer freezes a newer
  candidate before recruitment, this record must be superseded explicitly.
- PyPI availability statistics remain distribution activity, never participant
  outcomes.
