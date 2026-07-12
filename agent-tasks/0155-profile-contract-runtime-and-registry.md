# 0155: Profile contract runtime and built-in registry

- **Status:** Planned
- **Milestone:** v0.5.0 Council Profile
- **Priority:** P0
- **Size:** L
- **Dependencies:** 0154 contract freeze
- **DB schema:** no change

## Goal

Package standard-library validators and expose a deterministic, non-executable
registry for the built-in `council.discovery` manifest.

## Scope

- Add one current-convention validator module and packaged schema per contract.
- Export contracts through `src/pcl/contracts/__init__.py`.
- Add `src/pcl/profiles.py` and a package-data built-in manifest.
- Add `pcl profile list/show/validate` in text and JSON modes.
- Use `route_profile`, `runner_profile_id`, and `role_profile` consistently in
  public JSON/help/errors; snapshot help text that explains the distinction.
- Reject unknown keys/versions, duplicate IDs, invalid capabilities, missing
  package data, and executable hooks.
- Enforce mediated approval recording: an agent/system recorder of a human
  action requires conversation/Cockpit source provenance and a non-empty
  source ref.
- Enforce the frozen authorization data-class mapping and provider/cost scope;
  JSON Schema shape conformance alone is insufficient.

## Invariants

- Built-in only; arbitrary filesystem discovery is unsupported.
- Manifest is data-only and cannot import or invoke code.
- No provider SDK, runtime dependency, state mutation, or hidden network call.
- Discovery and finding order are deterministic.

## Acceptance

1. Canonical and negative contract fixtures pass manual validators.
2. list/show/validate have stable JSON and text snapshots.
3. Wheel/sdist contain every schema and the manifest.
4. Clean-wheel commands run without source checkout or network.
5. Existing CLI snapshots and full test suite pass.
