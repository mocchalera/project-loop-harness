# v0.5.2 Adoption Proof

## Claim under test

A developer who already uses a coding agent can add Project Loop Harness to a
real repository and reach one verified completion without learning the full CLI
or having the maintainer operate the loop.

This is an external first-use study, not telemetry and not a growth dashboard.
The repository is local-only; participants decide what sanitized evidence they
share.

Use the [participant kit](adoption-proof-v0.5.2-participant-kit.md) for the
invitation, candidate handoff, session boundary, and seven-day follow-up.

## Cohort

- five participants who are not the Project Loop Harness maintainer;
- at least three repository types (for example Python CLI/library, Node web app,
  and a mixed or differently structured project);
- real repositories the participant already understands;
- no production secrets, customer data, or destructive task is required;
- prior `pcl` users are excluded from first-use timing.

## Fixed task

The participant chooses one bounded, reversible change that normally takes
less than 20 minutes with their coding agent. The observer may explain the study
and safety boundary, but may not dictate routine `pcl` commands after the agent
prompt is submitted.

The participant starts from the README:

1. install `project-loop-harness` with `pipx` or `uv tool`;
2. run `pcl init --dry-run --json`, inspect it, then run `pcl init`;
3. run `pcl doctor --strict`;
4. give the README outcome prompt to their coding agent;
5. stop when a completion packet is emitted, a genuine human decision appears,
   or 30 minutes elapse;
6. optionally reuse `pcl` during the following seven days without prompting.

## Measures

Use wall-clock timestamps. Record `not reached` instead of inventing a duration.

| Field | Definition |
| --- | --- |
| install start | first install command begins |
| healthy setup | doctor has no placeholder, empty-command, or missing-finish-check finding |
| verified completion | `finish --emit-packet` returns `COMPLETED_VERIFIED` or `COMPLETED_WITH_RISK` |
| maintainer intervention | maintainer supplies a routine command, edits participant config, or repairs loop state |
| safety violation | agent crosses a declared human gate or performs an unauthorized destructive/external action |
| voluntary reuse | participant starts another `pcl` goal within seven days without study prompting |

## Success thresholds

- median install start → healthy setup: at most 5 minutes;
- verified completion: at least 4 of 5 participants within one session and 30 minutes;
- safety violations: 0;
- voluntary seven-day reuse: at least 2 of 5 participants;
- maintainer interventions: at most 1 per participant.

These thresholds are frozen before recruitment. They must not be weakened after
seeing results without clearly labeling a new experiment.

## Observation record

Create one sanitized JSON record per participant. Do not store names, repository
URLs, source code, prompts containing secrets, full transcripts, or credentials.
All five records must name the same candidate ID and candidate wheel SHA-256.

```json
{
  "contract_version": "adoption-observation/v1",
  "participant_id": "AP-001",
  "observed_on": "2026-07-20",
  "candidate_id": "v0.5.2-candidate-1",
  "candidate_sha256": "<64 lowercase hex characters>",
  "repository_family": "python",
  "install_method": "pipx",
  "first_time_user": true,
  "install_to_healthy_seconds": 180,
  "verified_completion": true,
  "completion_seconds": 900,
  "completion_outcome": "COMPLETED_VERIFIED",
  "maintainer_interventions": 0,
  "safety_violations": 0,
  "voluntary_reuse_day_7": null,
  "stop_reason": "none",
  "confusion_codes": []
}
```

Store approved records under `docs/evidence/adoption-proof-v0.5.2/`. A
participant may provide no artifacts; the outcome can still be counted as an
observer record, clearly labeled as such.

Allowed values are intentionally coarse:

- `repository_family`: `python`, `node`, `mixed`, `go`, `rust`, `other`;
- `install_method`: `pipx`, `uv-tool`, `venv-pip`, `other`;
- incomplete `completion_outcome`: `not_reached`, `blocked_human`,
  `setup_failed`, `completion_failed`, `participant_stopped`;
- `stop_reason`: `none`, `timeout`, `human_decision`, `setup_failure`,
  `completion_failure`, `participant_stop`;
- `confusion_codes`: `install`, `dry_run`, `config`, `agent_prompt`,
  `pcl_command`, `evidence`, `finish`, `human_gate`, `dashboard`, `other`.

Evaluate records without network access:

```bash
python scripts/evaluate_adoption_proof.py \
  --records-dir docs/evidence/adoption-proof-v0.5.2
```

Exit 0 means every frozen gate passes. Exit 1 means valid evidence is incomplete
or misses a threshold. Exit 2 means evidence is invalid and cannot be evaluated.
The evaluator requires all five healthy-setup durations before calculating the
median and refuses mixed candidate IDs or hashes.

## Result report

Report the denominator and every miss. Separate:

- observed participant outcomes;
- maintainer inference;
- internal test or demo evidence;
- unknowns and sample limitations.

PyPI downloads, GitHub clones, page views, stars, release publication, and CI
runs may describe distribution activity, but they are not participant outcomes
and do not count toward these thresholds.

## Current status

Protocol, participant kit, and deterministic evaluator are ready. Status:
external participant outcomes not yet collected. Therefore the repository
currently makes no claim that adoption has been proven.
