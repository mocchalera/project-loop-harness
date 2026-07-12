# 0158–0160 Claude Fable milestone review

Date: 2026-07-12

Scope: commits `b16efc3`, `d8b1a0c`, and `5f19c6d`

Verdict: **APPROVE WITH REQUIRED FIXES**

Claude Fable independently reviewed atomic ingest, replay and conflict handling,
audit behavior, Decision governance, authorization, offline fixture isolation,
and source/wheel/sdist execution against ADR-005 and the frozen Council Profile
contracts. The reviewer ran the full suite (935 passed, 1 skipped) and the 93
profile-specific tests.

## Required finding

`profile_authorization_revoked` was consumed during validation and replay, but no
governed interface produced it. Because authorization expiry is optional, an
accidental indefinite network or paid authorization could not be withdrawn
without forbidden direct database access. Add a human-gated,
provenance-recording `pcl profile authorize --revoke <EV-ID>` command before the
0162 adoption gate or any real provider use.

## Optional hardening adopted for 0161

- Anchor stored bundle audit to the immutable `profile_output_ingested` event's
  bundle digest, not only to the editable Evidence manifest.
- Report unlisted files added inside finalized bundle directories.
- Revalidate an authorized output path before creating its parent directory.

## Architecture assessment

The implementation remains model-independent, local-first, Evidence-first, and
human-governed. Staged copies are revalidated before atomic rename and database
commit; exact replay is mutation-free; proposal selection revalidates frozen
bytes and requires human provenance; authorization is basis-bound and re-emits
deterministically; fixture output uses the same production validation path and
contains no provider execution path.
