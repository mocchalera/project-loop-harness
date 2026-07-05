# Task 0072: Sensitive Omission and Safe Index Defaults

## Goal

Make the code index safe by default before improving anything else about
retrieval quality. Today `pcl index build` will happily index `.env` files,
private keys, and credential files if they exist in the working tree (the
only protections are directory ignores and gitignore awareness). An index
that can leak a secret into search results, impact receipts, or a future
context pack bridge is worse than no index. Sensitive omission must land
before the v0.2 Context Pack bridge work begins.

## Background

- `DEFAULT_CODE_INDEX_EXCLUDES` in `src/pcl/code_index.py` covers only
  directories (`.git`, `.venv`, `node_modules`, `.claude/`, ...). There is
  no filename- or pattern-based sensitive exclusion at all.
- `pcl.yaml` `permissions.agent_may_not_modify` lists `.env`, `.env.*`, and
  `secrets/`, but that is a write-protection list; the indexer never reads it.
- The 2026-07-05 review (v0.1.9 agenda) rated safety B- and named this the
  single most urgent gap: "検索精度より先に sensitive omission".

## Scope

- Add a default sensitive-exclusion pattern set applied during scan, before
  hashing or content reads. Minimum patterns:
  `.env`, `.env.*`, `*.pem`, `*.key`, `id_rsa`, `id_rsa.*`, `id_ed25519`,
  `id_ed25519.*`, `credentials*.json`, `.npmrc`, `.pypirc`, `*.p12`,
  `*.pfx`, `*.keystore`, `*.jks`, `.netrc`, `.aws/`, `secrets/`.
  Document the full list in `docs/code-context.md`.
- Matched files are recorded as ignored entries with
  `ignored_reason: "sensitive:<pattern>"` — never hashed, never content-read,
  never summarized, never searchable.
- Inherit `permissions.agent_may_not_modify` patterns from `pcl.yaml` into
  the index exclusion set automatically, with
  `ignored_reason: "sensitive:agent_may_not_modify"`. One configuration
  surface, two protections.
- Add `code_index.sensitive_exclude` (additional patterns) and
  `code_index.sensitive_include_override` (explicit opt-in list) settings in
  `pcl.yaml`. Any use of the override must emit a clear warning on stderr on
  every `pcl index build`, and the override usage must be recorded in the
  index run summary.
- Surface `sensitive_omitted_count` in:
  - `pcl index build` / `pcl index status` output (text and `--json`),
  - the index run summary JSON,
  - `context-receipt/v0` artifacts written by `pcl impact --diff`
    (additive field).
- `pcl code search` must never return a sensitive-excluded file, even if a
  stale index row exists from a build made before this task; guard at query
  time as well as scan time.

## Acceptance Criteria

- A fixture project containing `.env` (with a fake token), `server.pem`,
  `id_rsa`, `credentials.json`, and `.npmrc` shows all five files omitted
  with `sensitive:` reasons, and none of them appear in `pcl code search`
  results, impact receipts, or symbol summaries. A contract test enforces
  this, in the same spirit as the existing epistemic-honesty tests.
- The fake token string itself appears nowhere in any index table row,
  search output, or receipt artifact (assert by substring scan in the test).
- `agent_may_not_modify` patterns from `pcl.yaml` are honored by the indexer
  and covered by a test.
- Explicit override works, warns on stderr, and is recorded in the run
  summary; a test covers the warning and the recording.
- `sensitive_omitted_count` is present and correct in index status output
  and in receipts.
- `ruff check .` passes; full `python3 -m pytest` passes; `pcl init` smoke
  against a temp directory passes.
- No schema migration is added (reuse the existing ignored/summary JSON
  structures).
- No dependency is added.

## Do Not

- Do not implement content-based secret scanning (entropy analysis, token
  regexes inside file bodies). Pattern-based path exclusion only; content
  scanning is a possible later task once measured.
- Do not add embeddings, Tree-sitter, call graphs, or semantic retrieval.
- Do not bump contract versions; evolve `code-index/v0`, `code-search/v0`,
  and `context-receipt/v0` additively.
- Do not use raw SQL to mutate `.project-loop/project.db`.
- Do not read or parse generated dashboard HTML.
- Do not add hosted services, telemetry, or new runtime dependencies.
