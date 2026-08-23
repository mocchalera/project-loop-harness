# Contributing

## Source of truth: PCL state vs GitHub Issues

- **Authoritative:** `.project-loop/` PCL state (SQLite + event log), accepted
  `agent-tasks/*.md` specs, and recorded Evidence. The `pcl` CLI is the only
  state-mutation interface, and every mutation appends an event.
- **Projection:** GitHub Issues communicate current work and discussion to
  contributors and connected coding agents. They are a one-way,
  contributor-facing view of the authoritative state above — never a second
  workflow authority.
- Closing a GitHub Issue alone must not close a PCL target or rewrite
  historical Evidence. Reconciling the two is a deliberate human action taken
  through public `pcl` commands and committed records.
- Issue comments, labels, and open/closed state are discussion signals, not
  lifecycle mutations of PCL state.

### Stable mapping fields (`scripts/github-issue-map.json`)

Each entry maps one GitHub Issue to its authoritative counterparts using
stable identifiers and accepted anchors only — never mutable status:

| Field | Meaning |
|---|---|
| `issue` | GitHub issue number (mapping metadata, not an authority) |
| `title_hint` | Optional non-empty display title hint used as mapping metadata; not lifecycle authority |
| `anchors.agent_task_ids` | `agent-tasks/<id>-*` spec files that own the acceptance criteria |
| `anchors.repo_paths` | Committed docs/source/evidence paths that anchor the work |
| `acceptance_criteria_refs` | Accepted repo-local anchors for the issue's acceptance criteria |
| `pcl_entities.goals`, `pcl_entities.features`, `pcl_entities.tasks` | Optional PCL goal, feature, and task IDs used for live enrichment when local state exists |

Priority, status/lifecycle, task dependencies, last authoritative Evidence, and
relevant commits are derived from PCL state or accepted task/repository records
at render time, or shown as unavailable; they are never hand-maintained in this
file.

### Refreshing the GitHub-facing backlog view

```bash
PYTHONPATH=src python scripts/render_github_backlog.py --root . --format markdown
PYTHONPATH=src python scripts/render_github_backlog.py --root . --format json
```

The command is deterministic, offline, and read-only. It fails closed —
non-zero exit, no artifact written — on missing or duplicate anchors,
unresolvable PCL entity references, or stale-status contradictions. State
that is merely absent (no local `.project-loop/`) is labeled as unavailable
instead of invented. Generated output is a review artifact: publish it into
GitHub Issues manually, or commit it deliberately as a deterministic fixture
when a change requires one.

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
pytest
```

## Before opening a PR

```bash
pytest
ruff check src tests
make demo
```

## Design review checklist

- Does the change preserve CLI as the only state mutation interface?
- Does every mutation append an event?
- Does validation catch the failure mode being introduced?
- Is the dashboard generated deterministically?
- Is the implementation local-first and safe by default?
