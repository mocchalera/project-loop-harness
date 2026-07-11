# Adaptive Entry v0.4.2 Dogfood Report

- Date: 2026-07-11
- Project Loop target: G-0018 / T-0035
- Feature / Story / Test: F-0020 / US-0018 / TC-0037
- Review status: **human review required**

## Scope

Adaptive Entry was exercised against:

1. Project Loop Harness itself.
2. The committed HEAD of `project-loop-harness-starter`, expanded into
   `/tmp/pcl-v042-starter-dogfood.ew1d90` so the source checkout remained
   unchanged.

Both repositories used the current worktree implementation through
`PYTHONPATH=src`; no global editable install was changed.

## Route matrix

| Repository | Case | Input | Result |
|---|---|---|---|
| PLH | clear | approved Work Brief, configured lint/test | Direct / R0 / `clear_acceptance` |
| PLH | ambiguous | explicit unapproved Work Brief | Discover / R1 / `unapproved_brief_input` |
| PLH | high risk | approved Work Brief + `src/auth/login.py` | Assure / R3 / `auth_or_permission_change` |
| starter copy | clear | approved Work Brief, configured lint/test | Direct / R0 / `clear_acceptance` |
| starter copy | ambiguous | explicit unapproved Work Brief | Discover / R1 / `unapproved_brief_input` |
| starter copy | high risk | approved Work Brief + `src/auth/login.py` | Assure / R3 / `auth_or_permission_change` |

The Assure/R3 policy explanation resolved `verification_depth=independent`,
`execution_chunk_size=small`, and `checkpoint_frequency=high`, each sourced
from `risk_floor:R3`.

## Override behavior

The starter copy previewed and applied a Direct-to-Discover exception:

- preview changed no state;
- apply recorded E-0003 original recommendation, E-0004 original resolution,
  and E-0005 route override;
- one `route_override_recorded` event/outbox pair covered the transaction;
- `route current` verified the referenced hashes and returned Discover as the
  historical effective profile;
- an attempted Assure/R3-to-Direct downgrade failed with
  `route_override_forbidden_downgrade` and produced no override trace.

## Timing

Each repository ran 250 in-process `resolve_policy_for_target` iterations.

| Repository | p50 | p95 | max | Gate |
|---|---:|---:|---:|---|
| PLH | 1.337 ms | 1.471 ms | 5.265 ms | pass (<50 ms) |
| starter copy | 1.239 ms | 1.320 ms | 5.204 ms | pass (<50 ms) |

These measurements are local macOS/Python 3.13 observations, not production
telemetry.

## Integrity and tests

- `ruff check .`: pass.
- `git diff --check`: pass.
- Full suite: 813 passed, 1 skipped in 114.88 seconds.
- PLH strict validate: errors 0; 52 known advisory findings.
- PLH audit: 14 human-review anomalies, 0 repairable, 0 unsupported; delta from
  the canonical baseline is zero.
- Starter-copy strict validate: errors/findings 0.
- Starter-copy audit: anomaly 0; 15 DB/JSONL/outbox records aligned and all
  outbox rows delivered.

## Packaging smoke

A pre-release package-data smoke was run without changing the project version:

- wheel and sdist built successfully as 0.4.1 development artifacts;
- wheel/sdist contained the Work Brief, route recommendation, route override,
  adaptive policy resolution schemas, and default policy JSON;
- a clean virtual environment installed the wheel with `--no-index`;
- clean-wheel `pcl --help` and all packaged resource loaders succeeded.

The 0.4.2 version bump, final artifacts, and hashes belong to 0149b and have not
been performed.

## Confusion and residual gates

One operator mistake occurred in the temporary starter project: `pcl start`
created start-receipt E-0001, so the subsequently added Work Brief was E-0002.
Attempting to approve E-0001 failed clearly with
`work_brief_unknown_evidence`; using the Evidence ID returned by `brief add`
resolved it. No partial approval trace was written.

Only Python 3.13 is available locally. Python 3.10–3.12 and Windows locking
smoke remain CI evidence requirements. Most importantly, US-0018 remains draft:
an authorized human must review whether the route classifications and override
semantics are acceptable. This report does not approve route quality or
authorize v0.4.2 release preparation/publication.
