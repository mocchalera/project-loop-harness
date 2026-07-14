# 0166 local Skill usage improvement loop validation

Date: 2026-07-14

## Result

The local MVP is complete. `pcl report skill-usage` scans existing Codex,
Claude, and Cockpit JSONL logs on explicit invocation and emits only aggregate,
normalized usage and friction signals. It does not retain raw content or mutate
Project Loop state.

The implementation adds no dependency, database migration, network request,
daemon, watcher, or external transmission.

## Automated verification

```text
PYTHONPATH=src pytest -q tests/test_skill_usage_report.py
8 passed in 0.58s

ruff check .
All checks passed!

PYTHONPATH=src pytest -q
982 passed, 1 skipped in 197.15s

git diff --check
passed

PYTHONPATH=src python -m pcl validate --strict --json
ok: true

PYTHONPATH=src python -m pcl render --json
ok: true
```

Strict validation retains historical lifecycle and Evidence advisories that
predate task 0166; it reports no validation error.

## Real-machine dogfood

Approved window: 2026-06-14 through 2026-07-14.

```text
PYTHONPATH=src python -m pcl report skill-usage \
  --since 2026-06-14 --until 2026-07-14 \
  --output /tmp/pcl-skill-usage-dogfood.json --json

elapsed: 7.00 seconds
Codex files scanned: 569
Claude files scanned: 171
Cockpit files scanned: 29
parse errors: 0
agent Skill sessions: 176
agent sessions with PCL commands: 139
PCL commands detected: 5,666
distinct workspaces: 83
Cockpit control-plane tasks: 0
```

The report's privacy contract declares raw content, command arguments, session
identifiers, and workspace paths as not retained. A direct output scan for the
local home path, user name, token-shaped fixture, session/task identifier keys,
and raw command/cwd keys returned `privacy_matches=0`.

The generated report SHA-256 was
`c007ac6fd3770c1d8ed7e6a8020efa0bd017ecd54259e3563627322d916429a4`.

## Dogfood improvements captured during implementation

- Initial broad parsing took longer than 93 seconds. Streaming, memory-mapped
  fallback scanning, and an optional local `rg` accelerator reduced the same
  approved scan to 7.00 seconds without adding a dependency.
- Friction output is correlated to detected PCL tool-call IDs, preventing
  unrelated transcript errors and timeouts from being attributed to PCL.
- Shell search commands are not treated as Skill execution. Only file-reading
  commands that actually target `project-control-loop/SKILL.md` count.
- Unknown command text is excluded by a normalized command allowlist, so paths
  and arguments cannot become report labels.

## Interpretation boundary

Reported timeouts, command errors, help probes, and repeated commands are
observed signals, not proven product defects. The generated candidates are
advisory; a human must reproduce a signal as a fixture or regression test before
changing the product or Skill.
