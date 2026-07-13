# Alpha stability policy

Project Loop Harness is alpha software. This policy defines the compatibility
surface we intentionally protect while allowing the product to keep learning.

## Protected public contracts

Within a published minor release line, patches preserve these surfaces unless a
security or integrity defect requires a documented fail-closed correction:

- versioned JSON artifacts and their `contract_version` meanings;
- documented JSON response fields, with additive fields allowed;
- typed JSON error `code` values for documented failure cases;
- ordered forward migrations accepted by `pcl migrate`;
- the rule that state mutations go through `pcl` or internal services and append
  an event;
- the claims-not-facts boundary: Evidence and model output do not become human
  approval or deterministic Verification by implication.

A breaking artifact shape receives a new contract version. A documented JSON
field removal, type change, or typed error replacement requires at least a
minor release, release-note migration guidance, and a compatibility window when
the old behavior can be preserved safely.

For this policy, “documented” means the surface is named in a canonical contract
document linked from the README, such as `docs/dashboard-data-contract.md`,
`docs/agent-adapter-contract.md`, or `docs/workflow-contract.md`, or in a
packaged versioned schema exported by `pcl contract`. Examples, planning drafts,
and undocumented implementation fields do not create a compatibility promise.

Human-gated actions may become stricter in a patch when the existing behavior
can silently approve, execute, or complete unsafe work. Such changes must be
called out in release notes and covered by regression evidence.

## Migration policy

- Migrations are forward-only and run in recorded order.
- Migration status and preflight are inspectable before mutation.
- Unsupported integrity anomalies stop rather than being silently rewritten.
- There is no automatic downgrade or reverse-migration guarantee.
- A new database migration in this repository requires explicit human approval.

The physical SQLite table layout is internal. Consumers must use `pcl` JSON,
reports, versioned artifacts, or documented read-only bridges instead of
querying tables directly.

## Not stable public API

The following may change between minor releases:

- human-readable CLI prose, ordering, color, and punctuation;
- generated dashboard HTML markup and CSS;
- internal Python modules, functions, and class names;
- undocumented JSON fields;
- workflow templates marked experimental;
- Council Profile recommendations, which remain opt-in and advisory;
- repository documentation layout outside linked canonical documents.

`dashboard-data.json` and other versioned artifacts are governed by their own
declared contract version. The dashboard HTML itself is not machine context.

## Deprecation and removal

Deprecations should identify the replacement, the earliest removal release, and
the compatibility risk. Removal must not make a previously human-gated action
automatic. Security and integrity fixes may shorten a compatibility window, but
the release notes must explain why.

## Supported environments

The release CI and package metadata are the source of truth for supported Python
and operating-system combinations. A platform is not claimed compatible solely
because one local smoke test passed. MCP compatibility is tracked separately in
`docs/mcp-compatibility.md`.

## Reporting a contract regression

Include the `pcl` version, command, JSON output or typed error, project schema
version, and the smallest reproducible fixture. Do not include secrets,
credentials, production data, or `.project-loop/project.db` from a sensitive
project.
