# 0156 route binding — Claude Fable advice

**Reviewer:** Claude Fable 5, high effort, via AGI Cockpit  
**Cockpit task:** `a3d10279`  
**Date:** 2026-07-12  
**Mode:** design advice only; no edits

## Decision point

The frozen request schema requires a real
`route.recommendation_evidence_id`, while `pcl profile prepare` must remain
read-only. A freshly computed recommendation may not have an Evidence ID.

## Adopted recommendation

Keep `profile-run-request/v1` unchanged and require a previously recorded,
target-linked route recommendation. Missing state fails with
`profile_route_recommendation_missing` and an exact
`pcl route recommend ... --record` repair command.

Prepare independently reloads and validates the artifact, verifies its event
hash where present, reuses its recorded changed-path inputs, recomputes the
current recommendation, and distinguishes stale state from artifact drift.
Override requests bind the original recommendation Evidence, effective route,
and override Evidence hash separately.

This preserves read-only preparation, frozen-contract discipline, external
dereferenceability, and stable request-basis digests without inventing an ID.

