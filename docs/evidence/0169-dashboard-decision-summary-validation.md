# 0169 dashboard decision summary validation

Date: 2026-07-14

## Automated verification

- `PYTHONPATH=src pytest -q tests/test_dashboard.py`
  - Result: `21 passed in 3.80s`
- `PYTHONPATH=src pytest -q`
  - Result: `991 passed, 1 skipped in 236.25s`
- `PYTHONPATH=src ruff check .`
  - Result: `All checks passed!`
- `git diff --check`
  - Result: passed with no output.
- `PYTHONPATH=src python -m pcl validate --strict --json`
  - Result: `ok: true`; only pre-existing lifecycle/evidence advisories remain.
- `PYTHONPATH=src python -m pcl render --locale ja --json`
  - Result: dashboard HTML and dashboard-data JSON rendered successfully.

## Browser verification

A clean local project was initialized in `/tmp/pcl-decision-preview`. Five
Features were completed with approved Stories, passing Tests, and copied
Evidence so that `pcl next` produced a real `checkpoint_review` human gate.

The Japanese dashboard was opened and inspected with the Cockpit in-app
browser. The default, non-expanded operator summary showed:

- `判断すること`: the five completed Features reached the five-Feature review
  threshold, and the larger product direction should be reviewed before more
  major work;
- `選べる内容`: `承認 / 却下 / 保留 / 追加の証跡を確認`;
- no raw `pcl checkpoint record` command in the top summary.

The full command and audit detail remained available inside the collapsed
`詳細なProject Loop情報` section. The five-card desktop layout remained readable
without overlap or clipping.

## Contract checks

- `dashboard-data/v1` is unchanged.
- No SQLite schema or dependency changed.
- Decision questions and free-form fallback text are HTML escaped.
- The existing no-decision message remains unchanged.
