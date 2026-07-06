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
pcl context pack --task T-0001 --include-code-context --json
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
    "required_sections": ["machine_context_rules"],
    "required_sections_omitted": [],
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

`--include-code-context` is opt-in. Without the flag, context packs do not look
for code-context receipts and keep the same v1 payload shape. With the flag,
the pack resolves the latest `context_receipt` evidence row, loads that receipt
artifact, and embeds only a stable `code-context-summary/v0` under
`context_pack.code_context`. The receipt body is never inlined; it is referenced
through `code_context.receipt_ref.evidence_id`,
`code_context.receipt_ref.receipt_path`, and `source_paths`.

`source_commands` are read-only re-fetch commands. They are commands a reader
can run to reproduce the inputs this pack was built from, and they must not
create evidence rows, receipt artifacts, reports, exports, or other project
state. Code-context packs therefore do not list `pcl impact --diff --json` in
`source_commands`.

When `--include-code-context` is requested, the pack also includes a top-level
`suggested_refresh_commands` field. These commands are artifact-regenerating
suggestions for refreshing the underlying code-context evidence; they may
create new evidence or artifacts. Stale or missing code context suggests
`pcl index build --json` followed by `pcl impact --diff --json`; fresh code
context suggests an impact refresh command.

The embedded `code_context.refresh_replay` object explains how closely those
refresh commands preserve the previous receipt scope:

- `fidelity: "scope_preserving"` means PLH reconstructed the replay command
  from receipt facts such as `diff_source` and `base_ref`.
- `fidelity: "generic"` means PLH can suggest a normal refresh, but cannot
  reconstruct the prior scope, for example when the receipt used
  caller-provided diff text.
- `fidelity: "unavailable"` means there is no usable receipt scope to replay.

Scope-preserving replay reflects the modes PLH can infer from receipt facts,
including `--include-untracked`, `--all-changes`, `--staged`, `--unstaged`,
and `--base <ref>`. It remains a suggested command, not an attestation that the
pack generation reran impact.

The summary contains compact fields such as `diff_source`,
`receipt_ref`, `changed_file_count`, `excluded_changed_file_count`,
`sensitive_omitted_count`, `staleness_warnings`,
`untracked_omission_warning`, `included_total`,
`included_candidate_context_top`, `omitted_reason_counts`,
`verification_suggestions`, `relevance`, `receipt_age`, `age_warning`,
`refresh_replay`, and `sensitive_include_override_used`.
Candidate rows use the phrase `included as candidate context`; the summary
does not make cognition claims about those files.

`relevance` is stamped by the context-pack builder because it knows the pack
target and the receipt selection method. It is not produced by the pure receipt
summarizer. In v0.1.12, the only shipping selection scopes are:

- `scope: "unscoped_latest"`: the most recent context receipt was selected by
  recency and was not created for the pack target.
- `scope: "missing_receipt"`: no context receipt was available.

The only shipping binding strength is `binding_strength: "none"`, meaning no
caller or PLH mechanism asserted a target linkage. Future vocabulary reserves
`scope: "target_bound"` and `binding_strength: "caller_asserted"` for a
possible caller-labeled flow. A caller-asserted binding would be a caller label,
not a PLH-verified semantic relation between the receipt and the target. This
version does not implement `--for-task`, `--for-job`, or
`--require-bound-receipt` flags.

`receipt_age` records freshness facts for the embedded receipt:
`{"created_at": "...", "age_seconds": 123}`. Age is computed against a single
pack-build timestamp and is clamped at `0` if the receipt timestamp is in the
future. If `created_at` is missing or unparsable, `receipt_age` carries only
`created_at` and sibling `age_warning` states that age could not be computed.
When `age_seconds > 3600`, `age_warning` is present. The 3600s threshold is a
named, provisional threshold pending dogfood data, and it is not configurable.
These fields are factual freshness labels only; they are not a go/no-go signal.

The summary is bounded. `included_candidate_context_top` contains at most the
top 10 candidate paths by default plus `included_total`; omitted receipt rows
are folded into `omitted_reason_counts`. The full
`included_candidate_context` and `omitted` receipt arrays are not embedded in
the context pack.

When no receipt exists, `--include-code-context` still succeeds and returns a
`code_context` summary with `status: "missing_receipt"` plus next actions:
`pcl index build --json` and `pcl impact --diff --json`. The same commands are
exposed in `context_pack.suggested_refresh_commands`; they are not placed in
`source_commands`. The summary still includes `relevance` with
`scope: "missing_receipt"` and `binding_strength: "none"`.

`--max-tokens` is an approximate budget control. Section selection uses the
deterministic, dependency-free `charclass/v1` estimator:

- ASCII word runs count as `ceil(length / 4)`;
- CJK characters count one token each;
- whitespace runs count one token each;
- punctuation, symbols, and other non-whitespace characters count one token
  each.

The legacy `approx_char_limit` and `approx_chars_per_token` fields remain in
`budget` for compatibility, but they are not the section-selection algorithm.
`estimated_token_count` reports the estimator result for the final Markdown. On
success, required sections are guaranteed to be present in `markdown`.
`machine_context_rules` is always required. `code_context_safety` is also
required whenever `--include-code-context` is used. The payload exposes this
invariant through `required_sections` and `required_sections_omitted`; the
latter is always `[]` on success.

When a budget can fit the required sections but not every optional section, the
command returns a truncated pack with exact, deterministic `included_sections`
and `omitted_sections` metadata instead of slicing through a section. Whenever
`omitted_sections` is non-empty, the final Markdown includes:

```markdown
_Context truncated. Increase `--max-tokens` to include omitted sections._
```

If `--max-tokens` is too small for the title, required sections, and reserved
truncation note, the command fails with a typed usage error instead of
returning a noteless or safety-incomplete pack. JSON mode uses the standard
`ok:false` shape with `error.code: "context_pack_budget_too_small"` and details
including `required_sections`, per-required-section token estimates,
`max_tokens`, and `estimated_min_max_tokens` for retrying.

## Sections

Job packs render included sections in canonical order:

1. machine context rules
2. code context safety, only when `--include-code-context` is used
3. code context verification suggestions, only when available through `--include-code-context`
4. code context detail, only when available through `--include-code-context`
5. target job
6. workflow run
7. goal
8. jobs in this run
9. verifications
10. human queue
11. evidence
12. recent events
13. agent prompt

The target job table includes lease fields:
`assigned_agent_id`, `attempts`, `lease_expires_at`, and
`last_heartbeat_at`. The verifications table includes rubric-aware
`confidence_score` and `evidence_completeness` columns when a row claims
`rubric/v1`; rows without that contract leave those cells blank.

Task packs render included sections in canonical order:

1. machine context rules
2. code context safety, only when `--include-code-context` is used
3. code context verification suggestions, only when available through `--include-code-context`
4. code context detail, only when available through `--include-code-context`
5. target task
6. dependencies
7. dependents
8. goal
9. related feature, when linked
10. related defect, when linked
11. sibling tasks, when a goal is linked
12. recent events

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
- `machine_context_rules` and the opt-in `code_context_safety` section are
  required-section invariants, not ordinary priority winners. They are
  guaranteed in successful Markdown output; too-small budgets fail with
  `context_pack_budget_too_small`.
- For verifier job packs, `code_context_verification_suggestions` has higher
  priority than `code_context_detail`.

The selected profile name is returned as `role_profile`.

## Boundaries

- The command is read-only.
- It does not write context packs to disk in v1.
- It does not execute external agents.
- It does not add or require schema migrations.
- It does not read or parse `.project-loop/dashboard/dashboard.html`.
- It never executes `pcl impact` during pack generation.
- It does not run `pcl index build` or `pcl impact`; `--include-code-context`
  reads the latest existing receipt evidence only.
- It does not inline the full context receipt body.

Agents should use `pcl` JSON commands, reports, evidence paths, or
`.project-loop/dashboard/dashboard-data.json` for follow-up machine context.

## Release Notes

`context-pack/v1` no longer includes the old misleading
`pcl impact --diff --json` entry in `source_commands`. That command creates a
fresh context receipt, so it now belongs under `suggested_refresh_commands`
when `--include-code-context` is requested.

`code_context.refresh_replay` now labels refresh suggestions as generic,
scope-preserving, or unavailable. For git-based receipts, refresh commands
preserve replayable scope flags such as `--include-untracked`, `--base`,
`--staged`, `--unstaged`, and `--all-changes`.
