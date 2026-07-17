# 0191 Installed Skill Freshness Validation

## Field evidence

- Cockpit task: `9649a8d2`
- Adopter project: `/Users/mocchalera/Dev/kikulab-design`
- Observed installed Skill: older direct-route contract using inline
  `--evidence`, no `pcl start`, and incomplete Story/Test linkage guidance.
- Observed routing: `pcl next` selected older `F-0008` instead of current
  `F-0009` work.
- Observed audit health: ten registered Evidence source paths had hash drift
  after verification reports were rewritten in place.
- Positive behavior: user-corrected `TC-0020` was waived and replaced by
  `TC-0021`, preserving acceptance history.

## Red proof

```text
PYTHONPATH=src pytest -q tests/test_cli_init.py \
  -k 'stale_installed_skill or refresh_skill'

2 failed
- installation_skill_drift was absent
- --refresh-skill was not recognized
```

## Targeted verification

```text
PYTHONPATH=src pytest -q \
  tests/test_cli_init.py::test_doctor_reports_stale_installed_skill_with_targeted_refresh \
  tests/test_cli_init.py::test_init_refresh_skill_is_targeted_backed_up_and_idempotent \
  tests/test_code_index.py::test_eval_fixture_propose_preserves_strict_audit_log_integrity \
  tests/test_code_index.py::test_eval_retrieval_record_baseline_is_durable_and_deterministic \
  tests/test_migrations.py::test_metadata_schema_version_behind_applied_is_diagnosed_and_repaired

5 passed
```

```text
PYTHONPATH=src pytest -q \
  tests/test_cli_init.py tests/test_codex_plugin.py \
  tests/test_skill_command_examples.py

65 passed
```

```text
PYTHONPATH=src python -m ruff check \
  src/pcl/cli.py src/pcl/init_project.py src/pcl/validators.py \
  tests/test_cli_init.py

All checks passed!
```

```text
python ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  skills/project-control-loop

Skill is valid!
```

## Full regression

```text
PYTHONPATH=src pytest -q

1082 passed, 1 skipped in 342.50s
```

## Fresh initialization smoke

Target: `/tmp/pcl-refresh-smoke.pcZigB`

```text
PYTHONPATH=src python -m pcl init --target <target> --json
PYTHONPATH=src python -m pcl doctor --root <target> --strict --json
PYTHONPATH=src python -m pcl validate --root <target> --strict --json
PYTHONPATH=src python -m pcl render --root <target> --json

init: created=true, event_appended=true
doctor: ok=true, findings=[]
validate: ok=true, findings=[]
render: ok=true
```

## Adopter dry-run proof

`kikulab-design` was not mutated. The new read-only plan reported exactly three
writes:

1. append `project_skill_refreshed` to `.project-loop/events.jsonl`;
2. create the old-Skill backup at
   `.project-loop/reports/project-control-loop-skill-backups/e18299eb594c20139e01bf8d0da5a12272e08e9d49457d23d26257a97411a33a.md`;
3. update `.agents/skills/project-control-loop/SKILL.md`.

`pcl doctor --json` emitted `installation_skill_drift` with the dry-run and
apply commands. No apply command was run against the adopter project.
