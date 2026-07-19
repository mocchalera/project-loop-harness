# 0200: gap-report/v1 Harness Gap Evidence

- **Status:** Complete
- **Milestone:** Harness Engineering Feedback Loop
- **Priority:** P0
- **Size:** L
- **Dependency:** 0146 Work Brief, 0197 Harness Ablation, strict Evidence resolvers
- **Project Loop:** Goal `G-0058`, Task `T-0122`, Feature `F-0064`, Story `US-0062`, Test `TC-0135`
- **DB schema:** remains 8

## Goal

Add the one missing layer identified while reviewing the Harness Engineering
proposal: record the earliest failed handoff and a closed gap classification as
immutable, target-bound Evidence. Candidate lessons stay isolated until a
hash-bound human decision authorizes promotion; authorization must not claim
that the lesson has already been applied to its durable owner.

## Reviewed design corrections

The inherited Cockpit plan is accepted with these corrections:

1. Gap targets include observed execution boundaries (`workflow_run` and
   `agent_job`) in addition to Goal, Task, Feature, and Defect targets.
2. `pcl gap promote` records `gap_lesson_promotion_approved` with
   `application_status=pending`; it never edits AGENTS.md, Skills, tests, or
   other durable owners automatically.
3. Read paths verify exactly one anchor event, one target link, canonical path
   shape, regular-file identity, recorded bytes, and SHA-256 before returning a
   healthy report or accepting promotion.
4. Candidate lessons require cited Evidence before promotion so uncorroborated
   producer self-report cannot become approved policy by implication.

## Contract

`gap-report/v1` is a producer-authored claim artifact with:

- producer, timestamp, and a target;
- optional related completion-packet / Evidence / Workflow Run references;
- one `earliest_failed_handoff` with `stage` and `description`;
- one closed `gap_class`:
  `context`, `capability`, `domain_ownership`, `authority`, `proof`,
  `feedback_delivery`, or `worker_limitation`;
- zero or more candidate lessons in an object keyed by stable, structurally
  unique `lesson_id` values, each with a proposed `durable_owner` and
  supporting Evidence references.

The diagnosis is a claim, not a fact. `worker_limitation` remains especially
provisional; one report cannot establish a general model limitation.

## CLI scope

- `pcl contract validate --type gap-report/v1 FILE`
- `pcl gap add FILE --summary ... [--dry-run]`
- `pcl gap show --evidence E-XXXX`
- `pcl gap list [--target TYPE:ID] [--gap-class CLASS]`
- `pcl gap promote E-XXXX --lesson LESSON_ID --actor ... --reason ...`

Human-mediated promotion records actor, recorder, Cockpit/conversation source,
artifact hash, lesson digest, and pending durable-owner application. Non-human
promotion and unhealthy or uncited lessons fail closed.

## Acceptance

1. Packaged JSON Schema and hand-written validator agree and reject unknown
   fields, malformed IDs/real-date timestamps, invalid enums, duplicate raw
   JSON lesson keys, and non-finite JSON.
2. Add/dry-run/show/list are deterministic, target-bound, and zero-mutation on
   failure; strict reads surface tampering instead of trusting the file path.
3. Promotion is human-only, hash-bound, Evidence-corroborated, idempotent, and
   explicitly pending application.
4. Fresh `pcl init` installs a compact router contract once without adding a
   parallel `.plh/`, HARNESS.md, or harness.yaml structure.
5. No migration, dependency, completion-packet change, automatic durable-owner
   write, hosted service, or `pcl harness review/improve` aggregator is added.
6. Targeted tests, full pytest, Ruff, fresh-init/E2E smoke, strict validation,
   audit check, render, and PCL completion proof pass.

## Sources

- Cockpit task `e22916a5` and reviewed plan
- <https://github.com/lopopolo/harness-engineering>
- Harness Engineering `Improve One Harnessed Job` playbook
