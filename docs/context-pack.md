# Context Pack

`pcl context pack` builds a read-only, focused handoff for another agent.

It is intended for PM/orchestrator agents that need to pass just enough
project-loop context to a worker without dumping all local state, parsing
generated dashboard HTML, or reconstructing prompt/evidence paths manually.

## Command

```bash
pcl context pack --job J-0001
pcl context pack --job J-0001 --role verifier --max-tokens 12000 --json
pcl context pack --task T-0001 --json
```

Exactly one of `--job` or `--task` is required.

## Contract

JSON mode returns `context-pack/v1`:

```json
{
  "ok": true,
  "context_pack": {
    "contract_version": "context-pack/v1",
    "target": {"type": "agent_job", "id": "J-0001"},
    "reader_role": "verifier",
    "role_profile": "verifier",
    "token_estimator": "charclass/v1",
    "budget": {
      "max_tokens": 12000,
      "approx_char_limit": 48000,
      "approx_chars_per_token": 4,
      "token_estimator": "charclass/v1"
    },
    "approx_char_count": 1000,
    "estimated_token_count": 320,
    "truncated": false,
    "included_sections": ["machine_context_rules", "target_job"],
    "omitted_sections": [],
    "source_commands": [
      "pcl jobs read J-0001 --json",
      "pcl prompt job J-0001 --json",
      "pcl validate --json"
    ],
    "source_paths": [".project-loop/evidence/agent-runs/J-0001/prompt.md"],
    "markdown": "# Context Pack: J-0001\n..."
  }
}
```

Task packs use the same `context-pack/v1` contract with
`"target": {"type": "task", "id": "T-0001"}`. This is an additive evolution of
the v1 contract rather than a new contract version.

`--max-tokens` is an approximate budget control. Section selection uses the
deterministic, dependency-free `charclass/v1` estimator:

- ASCII word runs count as `ceil(length / 4)`;
- CJK characters count one token each;
- whitespace runs count one token each;
- punctuation, symbols, and other non-whitespace characters count one token
  each.

The legacy `approx_char_limit` and `approx_chars_per_token` fields remain in
`budget` for compatibility, but they are not the section-selection algorithm.
`estimated_token_count` reports the estimator result for the final Markdown.
When the budget is too small, the command returns a truncated pack with exact,
deterministic `included_sections` and `omitted_sections` metadata instead of
failing or slicing through a section.

## Sections

Job packs render included sections in canonical order:

1. machine context rules
2. target job
3. workflow run
4. goal
5. jobs in this run
6. verifications
7. human queue
8. evidence
9. recent events
10. agent prompt

The target job table includes lease fields:
`assigned_agent_id`, `attempts`, `lease_expires_at`, and
`last_heartbeat_at`. The verifications table includes rubric-aware
`confidence_score` and `evidence_completeness` columns when a row claims
`rubric/v1`; rows without that contract leave those cells blank.

Task packs render included sections in canonical order:

1. machine context rules
2. target task
3. dependencies
4. dependents
5. goal
6. related feature, when linked
7. related defect, when linked
8. sibling tasks, when a goal is linked
9. recent events

Task dependencies include a `satisfied` column. It is `yes` when the dependency
task status is `done`, `cancelled`, or `waived`; otherwise it is `no`.

## Role Profiles

Section selection is role-aware under tight budgets. Sections are selected by
profile priority, then rendered in canonical order.

- `implementer` is the default job profile and follows canonical job order.
- `verifier` prioritizes verifications, evidence, target job, and run jobs.
- `pm` prioritizes goal, human queue, workflow run, and verifications.
- Unknown or blank job roles fall back to `implementer`.
- Task packs currently use the `default` profile.

The selected profile name is returned as `role_profile`.

## Boundaries

- The command is read-only.
- It does not write context packs to disk in v1.
- It does not execute external agents.
- It does not add or require schema migrations.
- It does not read or parse `.project-loop/dashboard/dashboard.html`.

Agents should use `pcl` JSON commands, reports, evidence paths, or
`.project-loop/dashboard/dashboard-data.json` for follow-up machine context.
