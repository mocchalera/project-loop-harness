# Task 0066: Agent Registry And Job Leases

## Goal

Add a local agent registry and explicit job dispatch leases so `pcl` can track
which local agent owns a running job, enforce simple concurrency, and recover
expired work without background processes.

## Scope

- Add schema migration 003 with an `agents` table and additive lease columns on
  `agent_jobs`.
- Keep existing `agent_jobs.status` values and existing job completion,
  failure, and cancellation command semantics.
- Add `pcl agent register/list/read/update/retire` without removing or
  changing `pcl agent command`.
- Add `pcl jobs assign/lease/heartbeat/release/reap`.
- Evaluate lease expiry lazily at command time.
- Make `pcl jobs reap` the only mutation path for expired leases.
- Route `pcl next` to `pcl jobs reap` with `reap_expired_leases` when running
  jobs have expired leases.
- Add validation for missing agent references, expired running leases, retired
  agents with active leases, and active agents over concurrency.
- Update README, data model docs, example configs, and tests.

## Lease Boundary

`loop.max_lease_attempts` is the total number of expired lease attempts allowed
before blocking. The default is `2`: the first expired lease requeues the job
with `attempts = 1`; the second expired lease sets `attempts = 2`, blocks the
job, and opens a high-severity escalation.

## Acceptance Criteria

- `pcl agent register --name ... --role ... --adapter ... --json` returns
  `A-0001` and appends `agent_registered`.
- Duplicate agent names are rejected.
- Agent reads include `active_lease_count` and active job ids.
- Agent update requires `--reason` and appends `agent_updated`.
- Agent retire requires `--reason`, appends `agent_retired`, and rejects
  retirement while the agent holds an active lease.
- `pcl jobs assign` only assigns queued jobs to active agents and appends
  `job_assigned`.
- `pcl jobs lease` starts a queued job, respects max concurrency, records
  `lease_expires_at` and `last_heartbeat_at`, and appends `job_leased`.
- `pcl jobs heartbeat` extends an unexpired running lease and rejects expired
  leases with guidance to run `pcl jobs reap`.
- `pcl jobs release` returns a running job to queued, clears lease fields, and
  keeps `assigned_agent_id`.
- `pcl jobs reap` processes expired leases in job id order, requeues or blocks
  according to the lease boundary, and opens an escalation on exhaustion.
- `pcl jobs complete`, `pcl jobs fail`, `pcl jobs cancel`, and agent output
  ingestion clear lease fields when jobs leave active work.
- `pcl next --json` returns `type = "reap_expired_leases"`, command
  `pcl jobs reap`, and priority `44` when running leases are expired.
- `ruff check .` and full `pytest` pass.
- The lease demo flow proves first expiry requeues and second expiry blocks with
  an escalation visible in dashboard human decisions.

## Do Not

- Do not add dependencies.
- Do not add background processes, daemons, timers, or automatic reap loops.
- Do not let agents mutate SQLite directly.
- Do not change existing job status values.
- Do not require hosted services, cloud sync, telemetry, or paid APIs.
