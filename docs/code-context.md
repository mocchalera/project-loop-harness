# Explainable Code Context

Project Loop Harness includes a minimal dependency-free code context index for
auditable handoffs. It is a snapshot, not a replacement for the working tree.

The working tree remains the source of truth. The index records enough file
metadata and lightweight code signals for PLH to explain candidate context,
omissions, staleness, and suggested verification.

## Commands

Build an explicit snapshot:

```bash
pcl index build --json
pcl index build --json --include-files
```

Inspect the latest snapshot:

```bash
pcl index status --json
pcl index status --json --include-files
```

Run lexical search over indexed files:

```bash
pcl code search "query terms" --json
```

Explain likely impact from a diff and write a context receipt:

```bash
pcl impact --diff --json
pcl impact --diff --base main --json
pcl impact --diff --base auto --json
pcl impact --diff --staged --json
pcl impact --diff --unstaged --json
pcl impact --diff --include-untracked --json
pcl impact --diff --all-changes --json
git diff --no-ext-diff --no-textconv --name-status main -- | pcl impact --diff - --json
```

Show a compact context receipt summary:

```bash
pcl receipt show E-0001
pcl receipt show .project-loop/evidence/context-receipts/e-0001-impact-v0.json
pcl receipt show --latest
pcl receipt show E-0001 --json
```

Evaluate retrieval behavior against labels:

```bash
pcl eval retrieval --fixture tests/fixtures/retrieval_v0.json --json
pcl eval retrieval --fixture tests/fixtures/retrieval_v0.json --record-baseline --json
pcl eval retrieval --fixture tests/fixtures/retrieval_v0.json --compare-baseline --json
```

## Index Contract

`pcl index build --json` returns a summary `code-index/v0` payload by
default. This keeps agent-facing stdout small. The full per-file index detail
is always written to the deterministic `detail_path` under `.project-loop/`.
Use `--include-files` to restore the full inline payload when the caller really
needs every file, ignored path, and hash-skip entry on stdout.

```json
{
  "ok": true,
  "index": {
    "contract_version": "code-index/v0",
    "root_path": "/path/to/project",
    "git_head": "abc123",
    "file_count": 2,
    "indexed_bytes": 1200,
    "ignored_count": 3,
    "hash_skipped_count": 1,
    "sensitive_omitted_count": 1,
    "language_counts": {"python": 2},
    "staleness_warnings": [],
    "detail_path": ".project-loop/cache/code-index-detail.json",
    "event_appended": true
  }
}
```

`detail_path` and `--include-files` expose the full detail shape:

```json
{
  "contract_version": "code-index/v0",
  "root_path": "/path/to/project",
  "git_head": "abc123",
  "file_count": 2,
  "indexed_bytes": 1200,
  "ignored_count": 3,
  "hash_skipped_count": 1,
  "sensitive_omitted_count": 1,
  "language_counts": {"python": 2},
  "staleness_warnings": [],
  "detail_path": ".project-loop/cache/code-index-detail.json",
  "event_appended": true,
  "files": [
    {
      "path": "src/pcl/context.py",
      "language": "python",
      "size_bytes": 100,
      "mtime": 123456789,
      "sha256": "abc123",
      "line_count": 10,
      "indexed_content": "def pack_context_for_job(...):\n    ...\n",
      "symbol_summary": {
        "contract_version": "symbol-summary/v0",
        "symbols": [{"type": "function", "name": "pack_context_for_job", "line": 1}]
      },
      "test_hint": {
        "contract_version": "test-hint/v0",
        "is_test": false,
        "candidate_tests": [{"path": "tests/test_context.py", "reason": "filename_match"}]
      }
    }
  ],
  "ignored": [
    {"path": ".env", "ignored_reason": "sensitive:.env"},
    {"path": ".project-loop/", "ignored_reason": "default_ignore:.project-loop"}
  ],
  "hash_skipped": [
    {
      "path": "assets/logo.bin",
      "ignored_reason": "binary_file",
      "sha256": null,
      "hash_skipped_reason": "binary_file"
    }
  ]
}
```

The index is gitignore-aware when Git is available. In non-Git directories,
PLH applies root `.gitignore` patterns it can evaluate with the standard
library. Default exclusions include `.project-loop`, `.venv`, `node_modules`,
`dist`, `.git`, Python caches, binary files, files larger than the v0 size
limit, common agent/session state directories such as `.claude/`, `.agents/`,
and `.codex/`, and sensitive path patterns.

The default sensitive path patterns are:

- `.env`
- `.env.*`
- `*.pem`
- `*.key`
- `id_rsa`
- `id_rsa.*`
- `id_ed25519`
- `id_ed25519.*`
- `credentials*.json`
- `.npmrc`
- `.pypirc`
- `*.p12`
- `*.pfx`
- `*.keystore`
- `*.jks`
- `.netrc`
- `.aws/`
- `secrets/`

Sensitive paths are omitted before hashing or content reads. Their ignored
entries use `ignored_reason: "sensitive:<pattern>"`. Patterns inherited from
`permissions.agent_may_not_modify` use
`ignored_reason: "sensitive:agent_may_not_modify"`.

PLH is not a secret scanner. These omissions are conservative path-based guard
rails for agent handoffs, not a guarantee that arbitrary secret material has
been detected everywhere in a repository.

Large, binary, excluded, and sensitive paths are omitted from
`code_index_files`; the skip reason is preserved in the run summary and command
output.

Projects can override the agent/session default list with `pcl.yaml`:

```yaml
code_index:
  exclude:
    - .claude/
    - .agents/
  sensitive_exclude:
    - private-config.json
  sensitive_include_override:
    - local-fixture.pem
```

When `code_index.exclude` is present, that list replaces the default
agent/session excludes. Use `exclude: []` only when the project deliberately
wants those files indexed.

`code_index.sensitive_exclude` adds project-specific sensitive path patterns.
`code_index.sensitive_include_override` is an explicit opt-in escape hatch for
fixtures or other known-safe files that match sensitive patterns. Every
`pcl index build` with an override configured prints a warning to stderr, and
the latest run summary records `sensitive_include_override` and
`sensitive_include_override_used`.

`symbol-summary/v0` is deliberately shallow:

- Python: `def`, `async def`, and `class`.
- JavaScript/TypeScript: `function`, `class`, and simple `export` forms.
- Markdown: headings.

`test-hint/v0` uses filename and Python import conventions. It is a heuristic,
not a coverage statement.

## Status Contract

`pcl index status --json` returns a summary of the latest run plus staleness
warnings and `detail_path`. Like build, `--include-files` inlines the full
detail payload.

```json
{
  "ok": true,
  "index": {
    "contract_version": "code-index/v0",
    "stale": false,
    "file_count": 10,
    "ignored_count": 4,
    "hash_skipped_count": 1,
    "sensitive_omitted_count": 1,
    "indexed_bytes": 4096,
    "language_counts": {"python": 10},
    "last_run": {"id": "CI-0001", "index_version": "code-index/v0"},
    "current_git_head": "abc123",
    "staleness_warnings": [],
    "detail_path": ".project-loop/cache/code-index-detail.json"
  }
}
```

Staleness is based on Git HEAD, indexed paths, size, mtime, and ignored-path
count. Rebuild with `pcl index build --json` after meaningful code changes.

## Search Contract

`pcl code search <query> --json` returns `code-search/v0`.

```json
{
  "ok": true,
  "search": {
    "contract_version": "code-search/v0",
    "query": "context pack",
    "limit": 50,
    "result_count": 1,
    "results": [
      {
        "path": "docs/context-pack.md",
        "lines": [1],
        "snippet": "# Context Pack",
        "reason": "line contains all query terms",
        "snapshot_consistency": "fresh",
        "snapshot_consistency_reason": "current hash matches indexed hash"
      }
    ],
    "staleness_warnings": {
      "count": 0,
      "affected_paths": []
    },
    "git_head_warning": null
  }
}
```

Search is lexical and uses the current working tree contents for files present
in the latest index. If an indexed file is missing or unreadable, search may
match deterministic index metadata such as the path and symbol names so the
result can still report that file-state boundary. Hash-skipped paths recorded
in the latest snapshot summary may also appear when their current contents or
snapshot metadata match. Query terms match at file level, so terms may appear
on different lines. Results are ranked deterministically by relevance:
definition-like code hits rank above prose mentions, source and test files get a
small boost, prose files get a small penalty, and path order breaks ties.
Search also re-applies sensitive path exclusions at query time so stale index
rows from older builds cannot surface sensitive files.

Each search result includes `snapshot_consistency`:

- `fresh`: current file hash matches the indexed hash.
- `modified_since_index`: the file exists, but the current hash differs from
  the indexed hash.
- `missing_from_worktree`: the path is in the latest snapshot but no longer
  exists in the working tree.
- `not_hashed`: the path is in the latest snapshot without an indexed hash,
  such as a large or binary skip. These results include `hash_skipped_reason`
  when the snapshot recorded one.

The result-level `snapshot_consistency_reason` is a short file-state sentence,
not a claim about whether an agent read or understood the file.
`staleness_warnings.count` is the number of returned results whose
`snapshot_consistency` is not `fresh`; `affected_paths` lists those result
paths in result order. If the latest index run's Git HEAD differs from the
current HEAD, `git_head_warning` is populated once with the previous/current
hashes and the suggested command `pcl index build --json`. This is advisory;
search never rebuilds the index automatically.

## Impact Contract

`pcl impact --diff --json` returns `impact/v0` and writes a receipt artifact
under `.project-loop/evidence/context-receipts/`.

```json
{
  "ok": true,
  "impact": {
    "contract_version": "impact/v0",
    "diff_source": "worktree-vs-HEAD",
    "diff_provenance": {
      "source": "local-git-worktree",
      "attestation": "local-git",
      "command_shape": "git diff --no-ext-diff --no-textconv --name-status HEAD --"
    },
    "index_run": {"id": "CI-0001", "index_version": "code-index/v0"},
    "changed_files": [
      {
        "path": "src/pcl/context.py",
        "status": "M",
        "indexed": true,
        "language": "python",
        "reason": "changed file is present in the latest index"
      }
    ],
    "excluded_changed_files": [
      {
        "path": ".claude/session-001.json",
        "status": "M",
        "reason": "code_index.exclude:.claude/"
      }
    ],
    "likely_impacted": [
      {
        "path": "tests/test_context.py",
        "reason": "test_hint:filename_match+python_import",
        "confidence": 0.88,
        "source_path": "src/pcl/context.py"
      }
    ],
    "verification_suggestions": ["python3 -m pytest tests/test_context.py"],
    "omitted": [],
    "sensitive_omitted_count": 1,
    "staleness_warnings": [],
    "receipt_path": ".project-loop/evidence/context-receipts/e-0001-impact-v0.json",
    "evidence_id": "E-0001"
  }
}
```

`changed_files` contains only changed paths that are eligible for the code
index. Changed paths that match `code_index.exclude`, default index excludes,
or sensitive patterns are moved to `excluded_changed_files` with the exclusion
reason. This keeps agent/session state noise out of candidate ranking without
dropping it from the contract. `likely_impacted` and
`verification_suggestions` are computed only from indexable changed files.
Non-JSON text output prints excluded changed paths as a single summary line
with the count and first few paths.

`diff_source` states what PLH compared. Git-based modes use name-status diffs
and record the command shape in `diff_provenance`.

| Flags | `diff_source` | Compared state | Untracked included? |
|---|---|---|---|
| `--diff` | `worktree-vs-HEAD` | staged and unstaged tracked worktree changes vs `HEAD` | No |
| `--diff --base <ref>` | `worktree-vs-<ref>` | staged and unstaged tracked worktree changes vs `<ref>` | No |
| `--diff --staged` | `staged-vs-HEAD` | index vs `HEAD` using `git diff --cached` | No |
| `--diff --staged --base <ref>` | `staged-vs-<ref>` | index vs `<ref>` using `git diff --cached <ref>` | No |
| `--diff --unstaged` | `worktree-vs-index` | unstaged worktree changes vs the index | No |
| `--diff --include-untracked` | `worktree-vs-HEAD+untracked` | default tracked comparison plus `git ls-files --others --exclude-standard` | Yes |
| `--diff --base <ref> --include-untracked` | `worktree-vs-<ref>+untracked` | base-ref tracked comparison plus untracked files | Yes |
| `--diff --staged --include-untracked` | `staged-vs-HEAD+untracked` | staged tracked comparison plus untracked files | Yes |
| `--diff --unstaged --include-untracked` | `worktree-vs-index+untracked` | unstaged tracked comparison plus untracked files | Yes |
| `--diff --all-changes` | `all-changes-vs-HEAD+untracked` | all uncommitted tracked changes vs `HEAD`, plus untracked files | Yes |
| `--diff -` or `--diff <file>` | `provided-diff` | caller-provided diff text | Caller controlled |

`--include-untracked` never reads gitignored files; untracked paths come from
`git ls-files --others --exclude-standard`. Included untracked files are
represented as added files. Sensitive and configured exclusions are still
applied before candidate context is recorded, exactly as for tracked changes.
Receipts for including modes carry `untracked_included_count` and provenance
records `untracked_count`.

`--all-changes` is a convenience mode for default tracked changes plus
untracked files. It is anchored to `HEAD`; use `--base <ref>
--include-untracked` for alternate-base comparisons. `--staged --base <ref>` is
supported because Git's `git diff --cached <ref> --` semantics are explicit:
the index is compared to the chosen commit. `--unstaged --base <ref>` is
rejected because unstaged mode compares the worktree to the index by
definition.

`--base auto` resolves the comparison ref by trying `origin/HEAD` as a symbolic
remote default-branch ref, then local `main`, then local `master`. The resolved
ref is recorded as `base_ref`; `diff_provenance` also records that the value was
auto-inferred and lists the attempted refs. If none resolve, PLH returns a typed
`invalid_input` error naming `origin/HEAD`, `main`, and `master`.

If the stated diff is empty, PLH returns an `impact/v0` no-op payload with
`empty_diff_guidance`, writes no receipt artifact, and suggests likely next
operations for the selected mode, such as staging changes for `--staged`, using
`--staged` for staged-only changes when `--unstaged` is empty, adding
`--include-untracked` when untracked files are present, comparing against a
default branch, or checking a provided diff.

The receipt contract is `context-receipt/v0`. Its core fields are:

- `diff_source`: the same source label returned by `impact/v0`, with `base_ref`
  when applicable.
- `included_candidate_context`: files PLH provided as candidate context, with
  role, reason, confidence, language, indexed hash when available, and
  additive `snapshot_consistency` fields recorded at receipt time.
- `excluded_changed_files`: changed paths excluded from the index, with their
  exclusion reason.
- `omitted`: files PLH did not include and the recorded reason.
- `verification_suggestions`: suggested commands as objects with `id`,
  `command`, and `reason`.
- `sensitive_omitted_count`: the sensitive omission count from the index run.
- `staleness_warnings`: conditions that make the snapshot less current than
  the working tree.
- `untracked_included_count`: present only when the diff source explicitly
  includes untracked files.

Receipts are evidence artifacts. They record PLH output and reasons; they do
not make claims about agent cognition. Verification suggestion objects carry
only `id`, `command`, and `reason`; suggestion lifecycle state belongs outside
immutable candidate presentations. Existing factual fields such as git file
`status` on changed-file rows and summary availability `status` remain part of
their contracts.

Receipt `verification_suggestions` use object form:

```json
[
  {
    "id": "E-0001/VS-01",
    "command": "python3 -m pytest tests/test_context.py",
    "reason": "test_hint:path_token_match"
  }
]
```

Suggestion IDs are deterministic within a receipt: `<receipt evidence_id>/VS-<nn>`,
where `<nn>` is the 01-based, two-digit ordinal by suggestion position. They do
not use timestamps, randomness, database sequences, or a schema migration.
`reason` is short mechanical provenance from the suggestion source, such as a
test hint or staleness warning. Legacy receipts with string-list suggestions
remain valid on disk; the summary layer reports those entries with `id: null`
and the string as `command`.

## Receipt Summary

`pcl receipt show <ref>` renders a receipt through the shared
`code-context-summary/v0` model. `<ref>` can be a `context_receipt` evidence id
such as `E-0001`, an absolute receipt path, or a path relative to the project
root. `pcl receipt show --latest` resolves the newest `context_receipt`
evidence row.

Default output is ordered for fast human triage:

```text
# Context Receipt Summary

## Receipt
- evidence_id: E-0001
- receipt_path: .project-loop/evidence/context-receipts/e-0001-impact-v0.json
- created_at: 2026-07-05T00:01:00Z
- diff_source: worktree-vs-main
- base_ref: main

## Counts
changed: 2; excluded changed: 1; sensitive omitted: 1

## Staleness Warnings
- Indexed file metadata changed: src/pcl/cli.py.

## Untracked Omission Warning
Untracked files are not included in this diff source; add them to Git or provide an explicit diff with `pcl impact --diff - --json`.

## Included Candidate Context
included_total: 2
- src/pcl/cli.py: included as candidate context; role=changed_file; reason=changed file is present in the latest index; snapshot_consistency=modified_since_index
- tests/test_cli.py: included as candidate context; role=likely_impacted; reason=test_hint:filename_match; snapshot_consistency=fresh

## Omitted Reason Counts
- lexical symbol too common: 2
- not present in latest index: 1

## Verification Suggestions
- python3 -m pytest tests/test_cli.py [E-0001/VS-01]

## Next Recommended Command
`pcl index build --json`, then `pcl impact --diff --json`
```

`pcl receipt show --json` prints the `code-context-summary/v0` payload itself,
without wrapping it in a new command-specific shape. The human receipt view and
the optional `context_pack.code_context` section both derive from the same
summary model; neither path inlines the full receipt body or adds a
`safe_to_continue` field.

The summary also carries `refresh_replay`, an object with:

- `fidelity`: `scope_preserving`, `generic`, or `unavailable`;
- `commands`: artifact-regenerating refresh suggestions;
- `reason`: factual notes explaining the replay decision.

For git-based receipts, `refresh_replay` reconstructs the replayable diff
scope from `diff_source` and `base_ref`, including `--include-untracked`,
`--all-changes`, `--staged`, `--unstaged`, and `--base <ref>` where applicable.
For `provided-diff`, PLH cannot reconstruct the caller-provided diff text from
the receipt, so the refresh remains generic.

## Context Pack Bridge

`pcl context pack --include-code-context` links the latest context receipt into
normal task and job handoffs without inlining the receipt body.

The context pack resolves the newest evidence row with type `context_receipt`,
loads its JSON artifact, and converts it through a stable
`code-context-summary/v0` isolation layer. The summary is embedded under
`context_pack.code_context`; the original receipt remains referenced by
`receipt_ref.evidence_id`, `receipt_ref.receipt_path`, and the pack's
`source_paths`.

The summary is tolerant of missing or future receipt fields. Its stable safety
facts are:

- `diff_source`
- `receipt_ref` with `evidence_id`, `receipt_path`, and `created_at`
- `sensitive_omitted_count`
- `staleness_warnings`
- `excluded_changed_file_count`
- `untracked_omission_warning`
- `untracked_included_count` when untracked files were explicitly included
- `refresh_replay` with scope-preserving, generic, or unavailable refresh
  metadata

These facts are rendered in the opt-in `Code Context Safety` section with the
same pinned-priority budget mechanism used by `machine_context_rules`.

Additional summary fields include `changed_file_count`, `included_total`,
bounded `included_candidate_context_top` rows, `omitted_reason_counts`,
`verification_suggestions`, and `sensitive_include_override_used`.
`verification_suggestions` are summary objects with `id`, `command`, and,
when present, `reason`; legacy string-form receipt entries summarize with
`id: null`. Candidate wording is `included as candidate context`; PLH does not
make cognition claims about those files. `included_candidate_context_top`
contains at most the top 10 paths by default; omitted receipt rows are
aggregated by reason. The summary does not embed the full
`included_candidate_context` or `omitted` receipt arrays.

In context-pack markdown, `Code Context Safety` is non-droppable under the
existing section priority mechanism. `Code Context Verification Suggestions`
and `Code Context Detail` are ordinary budgeted sections. For verifier job
packs, verification suggestions have higher priority than the candidate
listing.

If no receipt exists, the command still returns a valid context pack with empty
receipt refs, a message, and next actions: `pcl index build --json` followed by
`pcl impact --diff --json`.

The bridge does not add schema, rebuild the index, run impact automatically,
make continuation claims, or expose a `safe_to_continue` field.

`likely_impacted` is capped at the top 20 candidates by confidence and stable
tie-breakers. Overflow candidates are recorded in `omitted` with
`omitted_type: "likely_impacted_candidate"` instead of being silently dropped.
Lexical symbol references are ignored when the symbol appears in more than
`max(10 files, 5% of indexed files)`, because such symbols are too common to
carry useful impact signal. Dropped symbols are recorded in `omitted` with
`omitted_type: "lexical_symbol_reference"`. `verification_suggestions` lists a
small targeted pytest command only when at most six candidate test files are
present; broader sets fall back to `python3 -m pytest`.

## Retrieval Evaluation

Fixtures use `retrieval-fixture/v0`. Checked-in fixtures should live under
`tests/fixtures/` and use one JSON object with a `tasks` array:

```json
{
  "contract_version": "retrieval-fixture/v0",
  "fixture_family": "real-history",
  "tasks": [
    {
      "id": "context-change",
      "diff": "diff --git a/src/pcl/context.py b/src/pcl/context.py\n...",
      "expected_files": ["src/pcl/context.py"],
      "expected_tests": ["tests/test_context.py"],
      "critical_context": ["src/pcl/context.py", "tests/test_context.py"],
      "metadata": {"source": "task-0069"}
    }
  ]
}
```

Fixture-level fields:

- `contract_version`: `retrieval-fixture/v0`. Checked-in fixtures must set this
  value. The loader also accepts a missing value for compatibility with early
  local fixtures.
- `tasks`: required non-empty array of task objects.
- `fixture_family`: optional label. Current checked-in families are
  `real-history` and `adversarial`.
- Other fixture-level fields are metadata and are ignored by the evaluator.

Task fields:

- `id`: optional stable task id. If omitted, eval uses `task-N`.
- `diff`: inline unified or name-status diff text. A task must include either
  `diff` or `query`.
- `query`: lexical search query. A task must include either `diff` or `query`.
- `limit`: optional search limit for `query` tasks; default is 50.
- `expected_files`: optional array of production/documentation paths expected
  to be retrieved.
- `expected_tests`: optional array of test paths expected to be retrieved.
- `critical_context`: optional array of paths whose absence is listed under
  `missing_critical_context`. When omitted, eval treats
  `expected_files + expected_tests` as critical.
- `expected_misses`: optional array of `{ "path": "...", "reason": "..." }`
  annotations for known baseline misses, such as a rename the current lexical
  retriever cannot resolve yet. These annotations document the baseline; they
  do not remove the path from recall accounting.
- Other task fields, including labels such as `family`, `case`,
  `assertion_note`, and `must_not_retrieve`, are metadata and are ignored by
  the evaluator.

Dogfood receipts become fixture candidates through a staging workflow:

```bash
pcl eval fixture propose --from-receipt E-0001 --json
```

The command reads a real `context_receipt` evidence row and writes an
UNLABELED `retrieval-fixture/v0` candidate to repo-root `fixtures/proposed/`.
That directory is a Git-tracked source staging area, not `.project-loop/`
runtime state. The candidate has one task, a synthetic unified diff touching
the receipt's `changed_files` paths, `diff_synthesized_from_receipt: true`, and
source receipt provenance (`evidence_id`, `created_at`, `diff_source`,
optional `base_ref`, and retrieved candidate paths). The synthetic diff is only
a replay handle because receipts do not store original diff text.

PLH never fabricates ground-truth labels. Proposed tasks carry
`labels_status: "unlabeled"` and empty `expected_files`, `expected_tests`, and
`critical_context` arrays. `pcl eval retrieval` refuses these candidates with a
typed error. A human must inspect the source receipt, fill the expected and
critical arrays, remove or change the unlabeled marker, and manually adopt the
fixture into `tests/fixtures/` with a normal Git move. There is no auto-labeling
or auto-adoption path.

Fixture evolution is additive in v0:

- New optional fields may be added without a version bump.
- Unknown fields must continue to evaluate without changing metric semantics.
- Existing field meaning, required-field changes, or metric semantics changes
  require a new fixture contract version.
- `retrieval-fixture/v0` should not grow thresholds, release gates, embeddings,
  Tree-sitter parsing, call graphs, daemons, or watchers.

The checked-in fixture families have different purposes:

- `retrieval_v0.json`: small synthetic coverage for code change, docs-only,
  and config-only tasks.
- `real-history`: derived from actual repository changes, currently following
  the `tests/fixtures/retrieval_real_history_v0.json` pattern. These fixtures
  measure ordinary retrieval quality against real change history.
- `adversarial`: synthetic cases intended to catch safety and trust
  regressions rather than average quality. The current
  `tests/fixtures/retrieval_adversarial_v0.json` covers sensitive-path
  omission, stale-index signaling, and an annotated renamed-file baseline miss.

`pcl eval retrieval --fixture <path> --json` returns `retrieval-eval/v0` with
precision, recall, false-positive rate, token cost estimate,
`missing_critical_context`, and per-task retrieved paths.

Metric fields:

- `precision`: true positives divided by retrieved paths, preserving the v0
  empty-denominator rule.
- `recall`: true positives divided by expected files/tests, preserving the v0
  empty-denominator rule.
- `false_positive_rate`: `(retrieved - true_positives) / retrieved`; empty
  retrieved denominators yield `null`.
- `token_cost_estimate`: deterministic `charclass/v1` estimate over retrieved
  paths' `indexed_content` from `.project-loop/cache/code-index-detail.json`.
  It is an estimate of indexed text volume, not a price or billing signal.
- `token_cost_unestimated_paths`: retrieved paths that are absent from the
  detail artifact's indexed content. They contribute `0` to the estimate and
  are listed explicitly.
- `missing_critical_context`: labeled critical paths not retrieved.

Task output may also include additive diagnostic fields used by adversarial
fixtures: `retrieval_source`, `staleness_warnings`,
`staleness_affected_paths`, `sensitive_omitted_count`,
`retrieved_snapshot_consistency`, `excluded_changed_files`, and
`expected_misses`.

### Baseline Lifecycle

`pcl eval retrieval --fixture <path> --record-baseline --json` runs the eval
and stores the full payload as normal evidence under
`.project-loop/evidence/retrieval-eval/`. Recording writes an evidence row and
the standard mirrored event in SQLite and `.project-loop/events.jsonl`; it does
not use a JSONL-only side channel.

Every baseline artifact carries `baseline_provenance` with these required
fields:

- `fixture_path`
- `fixture_content_hash` (sha256 of fixture bytes)
- `git_head`
- `index_run_id`
- `index_detail_hash` (sha256 of the code index detail artifact)
- `code_context_config_hash` (canonical effective `code_index` subtree)
- `pcl_version`
- `eval_contract_version` (`retrieval-eval/v0`)

Missing provenance inputs, such as no index run, missing index detail artifact,
or a non-Git target, are typed errors. In those cases no baseline artifact,
evidence row, or event is recorded.

`pcl eval retrieval --fixture <path> --compare-baseline --json` compares the
current eval with the latest recorded baseline whose `fixture_content_hash`
matches the current fixture. It reports current metrics, baseline metrics,
metric deltas, current provenance, and baseline provenance. The reported deltas
cover precision, recall, missing-critical-context count, false-positive rate,
and token cost estimate.

Comparison never crosses fixture hashes. If only a different fixture hash is
available, the command returns a typed not-comparable error naming the nearest
baseline and the hash mismatch. The comparison output is facts and deltas only:
no threshold logic, no verdict field, and no release gate.

CI runs `python3 scripts/run_advisory_retrieval_eval.py` after pytest. The step
initializes and indexes the checked-out project, evaluates the checked-in
real-history fixtures, evaluates the checked-in adversarial fixture against a
prepared temp project, and prints a compact JSON summary. When a local
retrieval-eval baseline exists, the script also prints the same comparison
facts as advisory output.

Advisory-vs-blocking boundary:

- Metric deltas never fail CI in v0.2.1.
- Eval infrastructure integrity failures do fail CI: eval command errors,
  fixture contract violations, unreadable fixtures, and provenance computation
  failures.
- Broken measurement is not advisory.

Semantic promotion gate: richer retrieval approaches such as semantic
retrieval, Tree-sitter parsing, or call-graph retrieval remain out of scope for
v0.2.1. Future promotion is evidence-driven: baseline history and fixture
coverage decide whether richer retrieval is justified, not enthusiasm. This
document deliberately defines no metric thresholds or release gates.
