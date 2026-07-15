# Evidence: 0182 v0.5.1 local release preparation

**Date:** 2026-07-15
**Scope:** Local release candidate only; no publication
**Human gate:** `ask_6d59ffeb5ebf` = `Continue`

## Result

The local v0.5.1 release candidate is ready for independent review. Package,
CLI, and MCP version surfaces report `0.5.1`; DB schema remains 8; runtime
dependencies remain empty; Python support metadata remains 3.10 through 3.13.

The accepted evaluation remains controlled owner dogfood. It is not external
adoption evidence and does not authorize a tag, push, GitHub Release, PyPI
write, pipx upgrade, or announcement.

## Controlled-evaluation input

- Cohort: `TRC-20260715-02`
- Valid resume: 6/6
- Broken-binding safe stop: 4/4
- Critical trust-boundary violations: 0
- No-index compatibility: 2/2
- Full transcripts received: 0
- Packet/Trace byte ratio: 0.344158 to 0.531553
- Accepted evidence: E-0432 and E-0433
- Human continuation receipt: E-0434

## Release artifacts

Built from the current local worktree with `python -m build` and checked with
`python -m twine check`.

| Artifact | SHA-256 | Twine |
| --- | --- | --- |
| `project_loop_harness-0.5.1-py3-none-any.whl` | `453e95ba20c54c1a1b6fdb0f272783a161913d8ef5ba2f0376de27a585d8e07f` | passed |
| `project_loop_harness-0.5.1.tar.gz` | `9becb45d47b90ca9b48d7f41a9a5c521c810322baa880db3d84eebf8162a40d7` | passed |

Local build directory:
`/tmp/pcl-v051-final3-dist.2quQPy`

## Verification

### Source and contract checks

- Source scratch init/doctor/strict validation/render: passed.
- Source no-index resume: no intent index and no claim refs, passed.
- Source valid binding: two bounded claims with `trust: unverified`, passed.
- Source invalid binding: no claims and
  `trace_claim_refs:invalid_binding`, passed.
- Targeted Trace/MCP checks before the final build: 46 passed, 1 skipped.
- Final distribution/Trace/retrieval regression checks: 11 passed.

### Installed wheel

A new virtual environment installed the final wheel with `--no-deps` and no
`PYTHONPATH`. `pcl --version` returned `pcl 0.5.1`. Scratch init, Evidence
copy/link, and resume covered all three paths:

- no-index compatibility: passed;
- valid hash/path/line-bound claims: 2 unverified refs, passed;
- invalid hash binding: claims omitted with typed reason, passed;
- `pcl doctor`, strict validation, and render: passed with 0 strict findings.

Wheel smoke directory:
`/tmp/pcl-v051-final3-wheel-smoke.nnkh3r`

### Source distribution

The extracted final sdist contains the v0.5.1 release note, Task 0182, master
Trace fixture, and both valid/invalid release-smoke bindings. Its source reports
`pcl 0.5.1`; packaged Trace and MCP tests passed 15 tests with 1 SDK-dependent
skip.

The repo-only distribution tests intentionally depend on canonical `skills/`
and `.github/`, which are outside the sdist contract, so they were verified at
the repository root rather than treated as extracted-sdist tests.

Extracted sdist directory:
`/tmp/pcl-v051-final3-sdist-smoke.3zU6MW/project_loop_harness-0.5.1`

### Final repository QA

- `PYTHONPATH=src python -m ruff check .`: passed.
- `git diff --check`: passed.
- `PYTHONPATH=src pytest -q`: 1039 passed, 1 skipped.
- `PYTHONPATH=src python -m pcl --root . --json validate --strict`: 0 errors;
  29 pre-existing lifecycle/Evidence warnings remain visible.
- `PYTHONPATH=src python -m pcl --root . render`: passed.

## Blockers found and fixed during preparation

1. The first sdist omitted `master-trace.md`. `MANIFEST.in` now includes test
   Markdown fixtures, and distribution tests freeze the master Trace plus both
   release-smoke bindings.
2. The first final full-suite run retrieved the new `*-index.json` fixture
   filenames as false positives in the unrelated code-index evaluation,
   lowering its precision to 0.3333. Renaming those fixtures to
   `*-trace-binding.json` restored the frozen 0.5 floor without changing the
   search implementation or evaluation threshold. The final full suite passed.

No acceptance threshold, failed evaluation denominator, trust boundary, or
publication invariant was weakened.

## Residual limitations

- Local verification used macOS arm64 and Python 3.13. Python 3.10-3.12,
  Windows, and remote CI were not rerun in this local task.
- Setuptools emitted known license-metadata deprecation warnings with a
  2027-02-18 deadline; artifact construction and Twine checks still passed.
- The worktree contains uncommitted and pre-existing concurrent changes. The
  hashes identify local artifacts but are not immutable release identities.
- Evaluation evidence proves controlled owner dogfood, not external-user
  adoption or market validation.
- Publication remains blocked on a separate human decision after independent
  review.
