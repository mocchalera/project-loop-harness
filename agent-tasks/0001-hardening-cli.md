# Task 0001: Harden the CLI

## Goal

Make the existing `pcl` CLI reliable enough for repeated local use.

## Read first

- `docs/architecture.md`
- `docs/data-model.md`
- `src/pcl/cli.py`
- `src/pcl/init_project.py`

## Scope

Implement or improve:

- typed exceptions instead of broad `Exception` handling;
- consistent exit codes;
- `--json` output for machine-readable commands;
- better validation messages;
- idempotent `pcl init`;
- protection against running commands before init;
- tests for every current command.

## Acceptance criteria

```bash
python -m pip install -e '.[dev]'
pytest
rm -rf /tmp/pcl-demo
pcl init --target /tmp/pcl-demo
pcl doctor --root /tmp/pcl-demo
pcl feature add --root /tmp/pcl-demo --name "Login" --surface "ui:/login"
pcl goal create --root /tmp/pcl-demo --title "Coverage"
pcl render --root /tmp/pcl-demo
```

All commands must pass and tests must cover happy path and failure path.

## Do not

- Do not add external dependencies unless necessary.
- Do not implement workflow runner in this task.
- Do not change schema without adding migration notes.
