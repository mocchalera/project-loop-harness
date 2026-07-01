# Task 0018: README Golden Path

## Goal

Update the user-facing README and golden-path documentation so a new operator can run the current Project Loop Harness end to end.

0017 made `pcl next` machine-readable and human-readable. The documentation should now show how `init`, workflow runs, jobs, verification, reports, dashboard, escalation, decision linkage, and guided next actions fit together.

## Scope

- Update `README.md` to match the implemented CLI/runtime through 0017.
- Add or update a golden-path document with copy-pasteable commands.
- Cover the happy-path feature-coverage loop.
- Cover the human decision branch using escalation/decision linkage.
- Explain guided `pcl next --json` fields and `pcl next --explain`.
- Point readers to reports and dashboard artifacts.
- Add a lightweight test or smoke coverage for the documented command path.

## Acceptance criteria

- README no longer describes the project as only a skeleton.
- README references tasks through 0018.
- Golden-path commands run in a temporary project.
- Human decision branch shows `pcl escalation open`, `pcl decision open --escalation`, `pcl decision resolve`, and `pcl escalation resolve --decision`.
- Guided next-action schema fields are documented.
- Validation and render commands are included.
- No schema migration is added.
- No generated dashboard HTML is hand-edited.

## Do not

- Do not add hosted services.
- Do not add external notification integrations.
- Do not change runtime behavior unless documentation verification exposes a bug.
- Do not make README depend on unreleased external packages.
