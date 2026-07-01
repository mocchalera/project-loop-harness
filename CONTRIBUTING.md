# Contributing

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
