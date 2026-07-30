# P1-A retained-capability remediation proof

Date: 2026-07-30

## Authority and boundary

- Independent READ-ONLY review: `bf15066b`
- Reviewed HEAD: `b54340e19f7a39cb65e5bf9106db0dfe645f6415`
- Review verdict: High 1 / Medium 3 / new Low 0, NO-GO
- Remediation source HEAD:
  `dfc55144732a6e6a121868ffe7be5984bdbed57a`
- Schema: 8
- Runtime dependencies added: 0
- Excluded: schema migration, dependency addition, P1-B, P1-C, telemetry,
  auth/billing, external writes, push, deploy, and Cockpit lifecycle mutation

`E-0018`, `E-0019`, `E-0020`–`E-0024`, their sources, and their durable
copies were not changed. The review made `E-0019` semantically insufficient;
this proof supersedes it with current, reproducible evidence for the reviewed
failure modes.

## Fail-first proof

The review-specific barrier, Git descriptor inheritance, projection,
legacy-ambiguity, and renderer-capability tests first produced:

```text
7 failed, 3 passed, 1 skipped in 2.94s
```

The passes were the barriers already protected before the final pre-commit
identity check and the public-renderer process lock. The skip is the
Linux-only Direct Git E2E on this Darwin host.

A further post-commit audit found that losing both projection and its pending
diagnostic could leak an untyped exception. Its new fail-first regression
produced:

```text
1 failed in 0.32s
```

It now returns typed exit 6 with `mutation_committed: true` and
`safe_to_retry_original: false`.

## Correct focused command

Every path in this command exists at the remediation HEAD:

```text
PYTHONPATH=src python -m pytest -q tests/test_direct_setup.py tests/test_render_lock.py tests/test_mutation_tail.py tests/test_start.py tests/test_event_outbox.py tests/test_mcp_server.py tests/test_dashboard.py tests/test_workflow_executor.py tests/test_workflows.py tests/test_workflow_proposals.py tests/test_locks.py tests/test_validation.py tests/test_command_guide.py tests/test_cli_init.py
```

Exact result:

```text
260 passed, 1 skipped in 28.02s
```

The review-specific GREEN command covers five real root-swap barriers, a real
Git repository through `pass_fds` plus `fchdir`, post-commit typed failure,
legacy ambiguity, and public/private renderer locking:

```text
PYTHONPATH=src python -m pytest -q \
  tests/test_direct_setup.py::test_direct_setup_root_capability_spans_commit_projection_and_tail \
  tests/test_direct_setup.py::test_direct_spec_root_fd_resolves_git_revision_after_rename \
  tests/test_direct_setup.py::test_direct_setup_git_revision_linux_e2e \
  tests/test_direct_setup.py::test_direct_setup_postcommit_projection_failure_is_typed_committed \
  tests/test_direct_setup.py::test_direct_setup_legacy_retry_rejects_same_request_ambiguity \
  tests/test_render_lock.py::test_public_renderer_blocks_on_another_process_exclusive_lock \
  tests/test_render_lock.py::test_lock_held_renderer_requires_live_matching_capability
```

Exact result:

```text
10 passed, 1 skipped in 3.84s
```

The additional projection-plus-diagnostic-loss regression passed separately:

```text
1 passed in 0.17s
```

## Full and static verification

```text
PYTHONPATH=src python -m pytest -q
1382 passed, 2 skipped in 327.85s (0:05:27)
```

The skips are:

1. the Linux-only `/proc/self/fd` Direct Git E2E on this Darwin host; and
2. external conformance through the prohibited optional MCP SDK dependency.

The production POSIX Git regression is not mocked: it creates a real Git
repository, renames its root, inherits the verified descriptor with
`pass_fds`, changes directory with `fchdir`, and resolves the same HEAD.

```text
PYTHONPATH=src python -m ruff check .
All checks passed!

PYTHONPATH=src python -m pytest -q tests/mcp/test_external_conformance.py
8 passed, 1 skipped in 0.88s

PYTHONPATH=src python -m pcl start --help
exit 0; --direct-spec is present

git diff --check
exit 0
```

All four Project Control Loop Skill copies have SHA-256:

```text
3f2489684eef46456d3136ef19a9bb80c25ff2fb3a69ce2a9f8e2846208e2409
```

The copies are:

```text
.agents/skills/project-control-loop/SKILL.md
skills/project-control-loop/SKILL.md
plugins/codex-project-loop/skills/project-control-loop/SKILL.md
src/pcl/templates/skills/project-control-loop/SKILL.md
```

## Fresh Git project smoke

Fresh root: `/tmp/pcl-p1a-retained-capability-smoke.bycu91`

- Git repository HEAD:
  `dfd0f64ca5a30b911a26c36a24b48599069ddcde`.
- `pcl init`: exit 0.
- First Direct start: exit 0, `status=started`, `mutated=true`, created
  `G-0001`, `T-0001`, and `E-0001`.
- Full-SHA-256 anchor:
  `EV-FEC2368D94119B855924954EFA1B96F93E1076A242E39630FC64C374136A7E77`.
- Stored initial and observed current Git revisions both equal the repository
  HEAD.
- Exact retry: exit 0, `status=already_started`, `mutated=false`, and
  `render.status=not_changed`.
- Changed input with the same request: exit 1,
  `direct_setup_idempotency_conflict`.
- Strict validate: exit 0, zero findings.
- Audit: exit 0, zero anomalies, DB/JSONL/outbox counts `17/17/17`, all outbox
  rows delivered.
- Standalone render: exit 0.
- Normal doctor: exit 0 with only the three expected fresh-template warnings.
  Strict doctor correctly returns exit 1 for those unconfigured template
  values.

## Worktree health before registering this proof

```text
PYTHONPATH=src python -m pcl.cli doctor --strict --json
exit 0; ok=true; active=0; historical=0

PYTHONPATH=src python -m pcl.cli validate --strict --json
exit 0; ok=true; active=0; historical=0

PYTHONPATH=src python -m pcl.cli audit check \
  --target T-0003 --since EV-E71D510409F1 --summary --json
exit 0; status=clean; matched anomalies=0; pending outbox=0

PYTHONPATH=src python -m pcl.cli audit check --summary --json
exit 6; exactly two superseded historical source-drift findings for
task:T-0002; current evidence corruption=0; pending outbox=0
```

## Immutable re-review checklist

- The root descriptor and device/inode capability remain live from secure spec
  read through validation, DB connect, final pre-commit check, SQLite commit,
  projection, and Direct tail.
- Before/after DB connect root replacement fails closed without mutation.
  Replacement after the final pre-commit check commits, projects, and renders
  only against the retained old root; the same-named replacement remains
  unchanged, and retry on the old root is a no-op.
- Darwin authority uses the stable `/.vol/<device>/<inode>` file-ID path, not
  `F_GETPATH` or the original name. Linux uses `/proc/self/fd/<fd>`.
- Git revision resolution inherits the verified descriptor with `pass_fds`
  and calls `fchdir` before Git. The Linux-only E2E is present; the portable
  production subprocess regression passes on Darwin.
- After SQLite commit, projection or retained-root diagnostic loss is typed
  exit 6 with `mutation_committed: true` and
  `safe_to_retry_original: false`.
- Public `render_dashboard` always acquires the common exclusive
  project-operation lock. The private lock-held route accepts only a live,
  same-root exclusive capability and rejects booleans, forged, expired, and
  other-root values.
- Standalone CLI, MCP, planning, workflow execution, normal mutation tail, and
  Direct tail share the canonical renderer wrapper; Direct avoids re-entry
  only through its verified private capability route.
- A legacy 48-bit retry is accepted only for one exact, fully verified
  same-request anchor. Same-request additional, corrupt, or multiple authority
  candidates conflict. Only a fully verified different-request prefix
  collision is ignored.
- Strict parser/path/resource boundaries, full-SHA-256 new anchors, receipt
  compatibility, event parity, schema 8, and dependency count 0 remain covered
  by the focused and full suites.
- P1-B and P1-C are absent.
