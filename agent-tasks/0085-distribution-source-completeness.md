# Task 0085: Distribution Source Completeness (P0)

**Status: retroactive record. Implemented in commit `204a857`
("Prepare v0.2 distribution and context refresh") before this spec was
filed. This file exists to keep the task ledger complete; do not
re-implement.**

## Why

The PyPI sdist for `project-loop-harness==0.1.12` included `tests/`
but not `docs/`. Unpacking the sdist and running `pytest -q -x` failed
at `tests/test_agent_adapter_contract.py::test_agent_adapter_docs_match_contract`
because `docs/agent-adapter-contract.md` was missing. PLH is a
docs-as-contract product; a published source artifact that cannot run
its own contract tests is a distribution honesty defect
(v0.1.12 review agenda, section 4.1).

## What was implemented (204a857)

- Added `MANIFEST.in` including `docs/`, `agent-tasks/`, `scripts/`,
  and `tests/` in the sdist, with prunes for local state directories
  (`.claude`, `.codex`, `.agents`, `.project-loop`, build outputs).
- Added `scripts/verify_sdist_contracts.py`: builds the sdist,
  unpacks it, and verifies the doc/contract test subset passes from
  the unpacked tree.
- Added a CI step running that script so an incomplete sdist fails
  the build.
- Documented the sdist/wheel role difference in `docs/distribution.md`
  and `docs/pypi-publishing.md`.

## Verification

- CI runs `scripts/verify_sdist_contracts.py` on every push.
- `tests/test_distribution.py` gained sdist content assertions.
- The fix reaches PyPI with the next release (v0.2.0); the 0.1.12
  sdist on PyPI remains incomplete and is superseded, not republished.
