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
pcl context pack --task T-0001 --include-code-context --require-bound-receipt --json
pcl context pack --task T-0001 --record-usage --json
```

Exactly one of `--job` or `--task` is required.

For an agent handoff that must carry code context, the canonical strict form is
`--include-code-context --require-bound-receipt` against a target that already
has a bound receipt (created with `pcl impact --diff --for-task` / `--for-job`).
It fails closed with `context_pack_bound_receipt_required` instead of silently
using an unrelated latest receipt.

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

Task packs include a `linked_evidence` field only when the task has evidence
rows recorded through `pcl evidence add --task T-XXXX`. Each row lists evidence
metadata and paths only: `id`, `type`, `summary`, `manifest_path`,
`member_paths`, `stored_paths`, and `created_at`. The generated Markdown renders
the same rows in a `Linked Evidence` section and never inlines member file
contents. `source_paths` includes the manifest path plus copied `stored_paths`
and original member paths so a reader can inspect the artifacts explicitly.
When there are no linked rows, the field and section are omitted so task packs
without linked evidence keep the same output shape as before.

Linked evidence summaries and commands are caller claims, not verified facts.
For model-derived artifacts such as intent indexes, the pack repeats that
claims-not-facts vocabulary and points readers to member paths rather than
treating model output as source of truth.

Task packs may opt into `--master-trace-context`. When exactly one copied
`master-trace/v0` and one copied `intent-index/v0` pass source-binding
validation, the section includes bounded `trace_claim_refs`,
`trace_claim_ref_omissions`, and `trace_claim_ref_budget`. Claims are explicitly
`unverified`; only Evidence/path/line coordinates are included, never trace or
resolved source-line text. Invalid or ambiguous bindings emit no claim refs and
retain their typed preflight status.

`--include-code-context` is opt-in. Without the flag, context packs do not look
for code-context receipts and keep the same v1 payload shape. With the flag,
the pack first queries `evidence_links` for the newest receipt bound to the
requested target with `link_role: "code_context"`:

- task packs query `target_type: "task"` and the task id;
- job packs query `target_type: "agent_job"` and the job id.

When a matching bound receipt exists, it is preferred over a newer unbound
receipt. If no matching bound receipt exists, the pack preserves the current
unscoped-latest fallback unless `--require-bound-receipt` is set. The selected
receipt artifact is loaded and embedded only as a stable
`code-context-summary/v0` under `context_pack.code_context`. The receipt body is
never inlined; it is referenced through
`code_context.receipt_ref.evidence_id`,
`code_context.receipt_ref.receipt_path`, and `source_paths`.

`--require-bound-receipt` is valid only with `--include-code-context`. When no
matching bound receipt exists, JSON mode returns `ok:false` with
`error.code: "context_pack_bound_receipt_required"` and details that include a
target-specific refresh command such as
`pcl impact --diff --for-task T-0001 --json` or
`pcl impact --diff --for-job J-0001 --json`. In this mode PLH does not silently
fall back to the unscoped latest receipt.

`source_commands` are read-only re-fetch commands. They are commands a reader
can run to reproduce the inputs this pack was built from, and they must not
create evidence rows, receipt artifacts, reports, exports, or other project
state. Code-context packs therefore do not list `pcl impact --diff --json` in
`source_commands`.

When `--include-code-context` is requested, the pack also includes a top-level
`suggested_refresh_commands` field. These commands are artifact-regenerating
suggestions for refreshing the underlying code-context evidence; they may
create new evidence or artifacts. Stale or missing code context suggests
`pcl index build --json` followed by a target-specific impact command; fresh
code context suggests a target-specific impact refresh command. These commands
preserve replayable diff scope where possible and add `--for-task` or
`--for-job` for the pack target.

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

`code_context.verification_suggestions` is additive over the original
command-only display: each summary item carries `id` and `command`, plus
`reason` when the receipt has object-form suggestions. Legacy string-list
receipt suggestions are still accepted and appear with `id: null`. Markdown
keeps the command first and may append the ID at the end.

`relevance` is stamped by the context-pack builder because it knows the pack
target and the receipt selection method. It is not produced by the pure receipt
summarizer. The shipping selection scopes are:

- `scope: "target_bound"`: a context receipt was selected through a matching
  `evidence_links` row for this pack target.

- `scope: "unscoped_latest"`: the most recent context receipt was selected by
  recency because no matching bound receipt was available. The summary includes
  an explicit warning.
- `scope: "missing_receipt"`: no context receipt was available.

Binding strength is `binding_strength: "caller_asserted"` only for
`target_bound` receipts created with `pcl impact --diff --for-task` or
`--for-job`. This is a caller label, not a PLH-verified semantic relation
between the receipt and the target. Unscoped fallback and missing-receipt states
use `binding_strength: "none"`.

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
`code_context` summary with `status: "missing_receipt"`, empty receipt refs, a
message, and next actions: `pcl index build --json` and a target-specific
impact refresh command. The same commands are exposed in
`context_pack.suggested_refresh_commands`; they are not placed in
`source_commands`. The summary still includes `relevance` with
`scope: "missing_receipt"` and `binding_strength: "none"`. Receipt-derived
summaries carry availability `status` values such as `from_receipt`,
`missing_receipt`, and `receipt_unavailable`; verification suggestion objects
carry only `id`, `command`, and `reason`.

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
6. linked evidence, only when rows are linked through `pcl evidence add --task`
7. dependencies
8. dependents
9. goal
10. related feature, when linked
11. related defect, when linked
12. sibling tasks, when a goal is linked
13. recent events

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
- In task packs, `target_task` has priority 850 and `linked_evidence` has
  priority 830. This keeps the task identity first under tight budgets while
  selecting linked artifacts before dependencies, related entities, sibling
  tasks, and recent events.

The selected profile name is returned as `role_profile`.

## Boundaries

- The command is read-only.
- The default remains fully read-only. Passing `--record-usage` is an explicit
  opt-in mutation that records exactly one local `context_pack_generated` event
  after a successful pack build. Recording uses the normal SQLite transaction
  and outbox projection path; a recording failure is returned as an error and
  is never silently skipped.
- KPI coverage derived from `context_pack_generated` includes only packs built
  with `--record-usage`. Dogfood measurement should consistently pass that flag.
- It does not write context packs to disk in v1.
- It does not execute external agents.
- Context-pack generation itself does not run migrations.
- It does not read or parse `.project-loop/dashboard/dashboard.html`.
- It never executes `pcl impact` during pack generation.
- It does not run `pcl index build` or `pcl impact`; `--include-code-context`
  reads `evidence_links`, evidence rows, and existing receipt artifacts only.
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
