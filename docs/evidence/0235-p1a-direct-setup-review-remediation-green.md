# P1-A Direct Setup independent-review remediation proof

Date: 2026-07-30

## Authority and boundary

- Independent READ-ONLY review: `bf15066b`
- Reviewed HEAD: `28de47881b56f3b80ee0724d324d38aec1b46a10`
- Review verdict: High 0 / Medium 5 / Low 2, NO-GO
- Remediation HEAD: `884010a9c7366c01f956d5256b52f34d1b3787cb`
- Schema: 8
- Runtime dependencies: none
- Excluded: schema migration, dependencies, P1-B, P1-C, telemetry,
  auth/billing, external writes, push, deploy, and Cockpit lifecycle mutation

`E-0018`, its source, and its durable copy were not changed. This proof
supersedes its non-existent focused path set with commands that resolve at the
remediation HEAD.

## Fail-first proof

The seven new independent-review invariant tests initially produced:

```text
6 failed, 1 passed in 11.93s
```

The one initial pass was the exact depth/node boundary test. The six failures
covered hostile parser normalization, hardlink rejection, root replacement,
full-width idempotency anchors with bounded legacy compatibility, and
cross-process renderer locking.

## Correct focused command

Every path in this command exists at the tested HEAD:

```text
PYTHONPATH=src python -m pytest -q tests/test_direct_setup.py tests/test_render_lock.py tests/test_mutation_tail.py tests/test_mcp_server.py tests/test_start.py tests/test_event_outbox.py tests/test_validation.py tests/test_command_guide.py tests/test_cli_init.py
```

Exact result:

```text
180 passed in 18.44s
```

The seven remediation-specific tests are:

```text
tests/test_direct_setup.py::test_direct_spec_cli_normalizes_surrogate_and_huge_integer_errors
tests/test_direct_setup.py::test_direct_spec_rejects_hardlinked_leaf_without_mutation
tests/test_direct_setup.py::test_direct_spec_enforces_exact_depth_and_node_boundaries
tests/test_direct_setup.py::test_direct_setup_root_swap_cannot_commit_old_spec_to_replacement_project
tests/test_direct_setup.py::test_direct_setup_anchor_uses_full_sha256
tests/test_direct_setup.py::test_direct_setup_legacy_anchor_retry_does_not_block_new_prefix_collision
tests/test_render_lock.py::test_cli_and_mcp_render_processes_share_direct_exclusive_lock
```

Their post-implementation result was:

```text
7 passed
```

## Full and static verification

```text
PYTHONPATH=src python -m pytest -q
1371 passed, 1 skipped in 361.11s (0:06:01)
```

The one skip is the optional external conformance route when the official MCP
Python SDK is unavailable. Adding its pinned test dependency was prohibited.

```text
PYTHONPATH=src python -m ruff check .
All checks passed!
```

```text
PYTHONPATH=src python -m pytest -q -rs tests/mcp/test_external_conformance.py
8 passed, 1 skipped in 1.21s
```

```text
PYTHONPATH=src python -m pcl.cli --help
exit 0; 64 lines

PYTHONPATH=src python -m pcl.cli start --help
exit 0; 24 lines; --direct-spec is present

git diff --check
exit 0
```

All four Project Control Loop Skill copies have SHA-256:

```text
7d68534d5096c1388e5f863d57d2e36bc522e80002153383cadeba8026f9ccdb
```

The copies are:

```text
.agents/skills/project-control-loop/SKILL.md
skills/project-control-loop/SKILL.md
plugins/codex-project-loop/skills/project-control-loop/SKILL.md
src/pcl/templates/skills/project-control-loop/SKILL.md
```

## Fresh initialized-project smoke

Fresh root: `/tmp/pcl-direct-remediation.yPexoP`

- `pcl init`: exit 0, initialized.
- First Direct start: exit 0, `status=started`, `mutated=true`, created
  `G-0001`, `T-0001`, `E-0001`.
- The deterministic anchor was
  `EV-4DDDC707EA32583813BB8CCD00150ABB2F55AB204CD52DB537B7AD666EB43C2B`
  (64 hexadecimal digest characters).
- Exact retry: exit 0, `status=already_started`, `mutated=false`, reused the
  same IDs, and returned `render.status=not_changed`.
- Modified Feature description with the same request: exit 1,
  `direct_setup_idempotency_conflict`.
- Created Story `US-0001` remained `draft`; Test `TC-0001` remained `planned`.
- Strict validate: exit 0, `ok=true`, zero findings.
- Doctor: exit 0; only the three expected fresh-template warnings.
- Audit: exit 0, zero anomalies, DB/JSONL/outbox counts `17/17/17`, every
  outbox row delivered.
- Standalone render: exit 0, `ok=true`.

## Worktree health before superseding E-0018

```text
PYTHONPATH=src python -m pcl.cli doctor --strict --json
exit 0; ok=true; active=0; historical=0

PYTHONPATH=src python -m pcl.cli validate --strict --json
exit 0; ok=true; active=0; historical=0

PYTHONPATH=src python -m pcl.cli audit check --json
exit 6; only superseded historical source drift for E-0013 and E-0014;
current evidence corruption=0; pending outbox=0
```

## Immutable remediation checklist

- Root directory FD and device/inode identity remain bound from secure spec
  read through authoritative connection, admission, and pre-commit checks;
  root replacement cannot cross-commit.
- Every canonical renderer caller enters the shared exclusive
  project-operation lock wrapper; Direct's already-held call uses only the
  internal non-reentrant route.
- Unpaired surrogates and oversized integer literals produce a typed
  `DirectSpecError`, JSON error output, exit 2, and empty stderr.
- New request anchors contain the full SHA-256 digest. The former 48-bit form
  is accepted only after full legacy receipt validation for the same request.
- Hardlinked Direct spec leaves are rejected with `st_nlink != 1`.
- Depth 8 / node 1024 are accepted; depth 9 / node 1025 are rejected.
- Existing start behavior, receipt top-level fields, event ordering, and
  projection/mutation-tail contracts remain covered by the focused and full
  suites.
