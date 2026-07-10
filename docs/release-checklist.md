# Release Checklist

Contract for every `project-loop-harness` release. Follow it in order; record
the outcome of each step in the release note. Steps marked **(trap)** encode
failures that actually happened in past releases — do not skip them.

## 1. Pre-flight

- [ ] All tasks for the milestone are merged to `main` and pushed; CI is green.
- [ ] **(trap)** Editable install points at the canonical repo, not a deleted
      worker worktree: `pip show project-loop-harness | grep Location` must
      resolve under `~/Dev/project-loop-harness`. If not:
      `pip install -e '.[dev]'` from the canonical repo. Symptom otherwise:
      previously-green `main` suddenly fails ~6 guarded-executor subprocess
      tests with exit 1.
- [ ] `SECURITY.md` supported-versions table matches the release line being
      published.
- [ ] `TASKS.md` lists every shipped `agent-tasks/` spec for this release.

## 2. Version bump

- [ ] Bump `version` in `pyproject.toml`.
- [ ] `tests` do not hardcode the version string (`test_cli_version` reads
      `pcl.__version__`); grep for the old version to catch strays:
      `grep -rn "<old-version>" src/ tests/ pyproject.toml`.
- [ ] Write the release note: scope, task IDs, semantic changes (e.g. evidence
      health semantics), CI matrix result, verification evidence.

## 3. Local verification

- [ ] `ruff check .`
- [ ] `pytest` (full suite) from the canonical repo.
- [ ] `pcl validate --strict --json` → `ok: true` on a scratch project
      (`pcl init` in a temp dir; note `pcl init` takes no positional argument).
- [ ] `pcl render --json` succeeds on the scratch project.

## 4. Build and packaging contracts

- [ ] `python -m build` (sdist + wheel).
- [ ] `twine check dist/*`.
- [ ] sdist contract: unpack the sdist and confirm `docs/` and `agent-tasks/`
      are included; `test_agent_adapter_docs_match_contract` passes from the
      unpacked sdist. **(trap)** Inside the sdist, the 3 `test_distribution`
      cases that depend on `.github/` / wheel build are expected to fail —
      that is outside the contract and normal.
- [ ] Fresh-venv wheel smoke: new venv → `pip install dist/*.whl` →
      `pcl --version` → `pcl init` in a temp dir → `pcl validate --strict
      --json` reports the expected schema version and `consistent: true`.
      **(trap)** Run this smoke in a clean environment; a polluted
      `PYTHONPATH` makes wheel-install tests fail spuriously.

## 5. Publish

- [ ] Tag `vX.Y.Z` on the release commit; push the tag.
- [ ] Create the GitHub Release (not draft) with the release note.
- [ ] Trusted publishing workflow publishes to PyPI — wait for completion.

## 6. Post-publish verification

- [ ] PyPI shows the new version as latest, with both wheel and sdist.
- [ ] Fresh venv: `pip install project-loop-harness==X.Y.Z` →
      `pcl --version` → init/validate smoke.
- [ ] Update local pipx: `pipx upgrade project-loop-harness` (or install).
      **(trap)** A stale pipx `pcl` shadows the editable install and has
      caused old-schema `pcl migrate` runs against live DBs in the past.
- [ ] Update the handoff memory / session log with the release record.
