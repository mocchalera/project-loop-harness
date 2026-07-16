# Dashboard inline card details acceptance evidence

Date: 2026-07-16

Scope: Goal `G-0052`, Task `T-0107`, Feature `F-0054`, Story `US-0052`,
and Test `TC-0117`.

## Accepted behavior

- The five operator-summary cards (`Now`, `Done`, `Next`, `Human needed`, and
  `Risks`) are native `<details>/<summary>` disclosures.
- Clicking a card reveals its related Goal, Task, Feature, Test, Evidence,
  Decision, or risk fields inside that card. Review does not depend on a
  fragment jump to the lower tables.
- The closed card keeps the existing concise summary.
- The opened card uses the available row width and a responsive detail grid.
- The dashboard remains script-free and static. `dashboard-data/v1` is
  unchanged; all additional detail is derived only while rendering HTML.
- Raw commands remain in the advanced Project Loop section.

## Automated verification

```text
PYTHONPATH=src python -m pytest -q \
  tests/test_dashboard.py::test_dashboard_operator_cards_expand_referenced_details_in_place
1 passed

PYTHONPATH=src python -m pytest -q \
  tests/test_dashboard.py tests/test_dashboard_data_contract.py
26 passed

PYTHONPATH=src python -m ruff check .
All checks passed!

PYTHONPATH=src python -m pytest -q
1080 passed, 1 skipped in 218.71s

PYTHONPATH=src python -m pcl --root . --json doctor
{"errors": [], "findings": [], "ok": true, "warnings": []}

PYTHONPATH=src python -m pcl --root . --json validate
{"errors": [], "findings": [], "ok": true, "warnings": []}
```

## Browser verification

AGI Cockpit's task-scoped browser opened the generated `dashboard.html`.

- Clicking the `Done` summary changed the same card to
  `<details ... data-operator-card="done" open>`.
- The expanded card displayed Feature `F-0053`, Test `TC-0116`, Evidence
  `E-0482`, their statuses, scenario, expected result, summary, and path in
  place.
- The collapsed narrow-panel view rendered as a single column without
  horizontal clipping.
- The expanded wide view gave the active card the full row and rendered its
  detail groups in responsive columns.

Visual artifact:
`output/playwright/0186-dashboard-inline-cards-expanded.png`.
