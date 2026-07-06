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
git diff --no-ext-diff --no-textconv --name-status main -- | pcl impact --diff - --json
```

Evaluate retrieval behavior against labels:

```bash
pcl eval retrieval --fixture tests/fixtures/retrieval_v0.json --json
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

`diff_source` states what PLH compared:

- `worktree-vs-HEAD`: the default for `pcl impact --diff`. PLH runs a
  config-independent `git diff --no-ext-diff --no-textconv --name-status HEAD --`
  shape and compares tracked staged and unstaged working-tree changes against
  `HEAD`.
- `worktree-vs-<ref>`: used by `pcl impact --diff --base <ref>`. PLH validates
  `<ref>` as a commit-ish before diffing and records `base_ref` in both impact
  JSON and the receipt.
- `provided-diff`: used when the caller provides diff text with `--diff -` or a
  diff file path. PLH records the source as caller-provided and cannot attest
  that the text matches the current working tree.

Untracked files are not part of `worktree-vs-HEAD` or `worktree-vs-<ref>`
diffs. Future modes may add `--staged`, `--unstaged`, and
`--include-untracked`, but those flags are not part of `impact/v0` today.

If the stated diff is empty, PLH returns an `impact/v0` no-op payload with
`empty_diff_guidance`, writes no receipt artifact, and suggests likely next
operations such as comparing against a default branch or providing an explicit
diff.

The receipt contract is `context-receipt/v0`. Its core fields are:

- `diff_source`: the same source label returned by `impact/v0`, with `base_ref`
  when applicable.
- `included_candidate_context`: files PLH provided as candidate context, with
  role, reason, confidence, language, indexed hash when available, and
  additive `snapshot_consistency` fields recorded at receipt time.
- `excluded_changed_files`: changed paths excluded from the index, with their
  exclusion reason.
- `omitted`: files PLH did not include and the recorded reason.
- `sensitive_omitted_count`: the sensitive omission count from the index run.
- `staleness_warnings`: conditions that make the snapshot less current than
  the working tree.

Receipts are evidence artifacts. They record PLH output and reasons; they do
not make claims about agent cognition.

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

These facts are rendered in the opt-in `Code Context Safety` section with the
same pinned-priority budget mechanism used by `machine_context_rules`.

Additional summary fields include `changed_file_count`, `included_total`,
bounded `included_candidate_context_top` rows, `omitted_reason_counts`,
`verification_suggestions`, and `sensitive_include_override_used`. Candidate
wording is `included as candidate context`; PLH does not make cognition claims
about those files. `included_candidate_context_top` contains at most the top 10
paths by default; omitted receipt rows are aggregated by reason. The summary
does not embed the full `included_candidate_context` or `omitted` receipt
arrays.

In context-pack markdown, `Code Context Safety` is non-droppable under the
existing section priority mechanism. `Code Context Verification Suggestions`
and `Code Context Detail` are ordinary budgeted sections. For verifier job
packs, verification suggestions have higher priority than the candidate
listing.

If no receipt exists, the command still returns a valid context pack with
`code_context.status: "missing_receipt"` and next actions:
`pcl index build --json` followed by `pcl impact --diff --json`.

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

Fixtures use `retrieval-fixture/v0`:

```json
{
  "contract_version": "retrieval-fixture/v0",
  "tasks": [
    {
      "id": "context-change",
      "diff": "diff --git a/src/pcl/context.py b/src/pcl/context.py\n...",
      "expected_files": ["src/pcl/context.py"],
      "expected_tests": ["tests/test_context.py"],
      "critical_context": ["src/pcl/context.py", "tests/test_context.py"]
    }
  ]
}
```

`pcl eval retrieval --fixture <path> --json` returns `retrieval-eval/v0` with
precision, recall, and `missing_critical_context`. This is the promotion gate
for richer retrieval work: v0 intentionally avoids embeddings, Tree-sitter,
call graphs, semantic retrieval, daemons, and file watchers.
