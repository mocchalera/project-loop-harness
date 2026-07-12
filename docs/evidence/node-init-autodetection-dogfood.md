# Node initialization auto-detection dogfood

Date: 2026-07-12

## Scenario

A fresh temporary copy of the UTSURO Node project was initialized through a
single `pcl start` command. No `pcl.yaml` was supplied or edited by a human.

## Observed configuration

- `package.json` name `utsuro-puzzle` became `project.name`.
- `project.type` became `node`.
- Existing `lint` and `test` scripts became `npm run lint` and `npm run test`.
- Missing `typecheck`, `e2e`, and `build` scripts remained unconfigured.
- `install`, `dev`, and release-oriented scripts were not adopted.

## Completion result

After creating a local Git snapshot required by completion-packet provenance,
`pcl finish --emit-packet --goal G-0001` ran both detected commands successfully.
The completion packet outcome was `COMPLETED_VERIFIED` with Evidence `E-0004`.

The first finish attempt stopped before command execution because the temporary
copy was not yet a Git repository. This was the expected provenance guard and
did not require changing the generated Node configuration.

Temporary verification root:
`/private/tmp/pcl-node-autodetect-litM00`

## Regression verification

- `PYTHONPATH=src pytest -q tests/test_cli_init.py tests/test_start.py -x`:
  35 passed.
- `ruff check src/pcl/init_project.py tests/test_cli_init.py tests/test_start.py`:
  passed.
- `PYTHONPATH=src pytest -q`: exit 0 across 957 collected tests
  (956 passed, 1 skipped).
