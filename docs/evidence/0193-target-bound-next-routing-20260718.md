# 0193 Target-Bound `pcl next` Verification

Date: 2026-07-18 (Asia/Tokyo)

## Reviewed plan

Claude Fable produced the concrete plan after inspecting the CLI parser,
`next_action` cascade, `pcl resume` target selection, start/dashboard/MCP
callers, command guide, and related tests. Codex accepted these choices:

- `pcl next --target <T-XXXX|G-XXXX>` uses the same bare-ID grammar as
  `pcl resume --target`.
- Unbound cross-Goal ambiguity returns a guided `select_target` action with
  exit 0 instead of raising through dashboard/MCP callers.
- Ambiguity is detected at Goal boundaries; deterministic priority remains
  valid within one Goal.
- No database migration or dependency addition is needed.

Codex narrowed one boundary before implementation: project-wide human and
safety gates retain precedence, while ordinary workflow and backlog actions
must belong to the explicit Task or Goal. An unrelated workflow is not treated
as a global blocker.

## Implemented slice

- Added optional exact target binding to the CLI and internal next-action
  router.
- Added target resolution, terminal-target handling, target-scoped workflow
  and Task routing, and additive `target_binding` / `routing_scope` metadata.
- Added deterministic `select_target` output with one candidate per Goal.
- Bound `pcl start` to its newly created Task and preserved null commands when
  active work requires target selection.
- Added human-readable candidate rendering and updated the CLI help snapshot.

## Verification

### Focused contract and integration suite

```text
PYTHONPATH=src python -m pytest \
  tests/test_next_actions.py tests/test_start.py tests/test_resume.py \
  tests/test_golden_path.py tests/test_presentation.py tests/test_dashboard.py \
  tests/test_mcp_server.py tests/test_skill_command_examples.py \
  tests/test_baseline_fixtures.py -q

139 passed in 20.71s
```

### Full regression suite

```text
PYTHONPATH=src python -m pytest -q

1089 passed, 1 skipped in 205.14s
```

### Static and patch checks

```text
PYTHONPATH=src python -m ruff check .
All checks passed!

git diff --check
exit 0
```

### Fresh-project smoke

Scratch root: `/tmp/pcl-next-0193.0Szi44`

- `pcl init`, `doctor`, strict `validate`, and `render` exited 0.
- Two Goals with one actionable Task each produced `type = select_target`,
  `command = null`, and deterministic candidates `T-0001`, `T-0002`.
- `pcl next --target T-0002 --json` produced `type = work_on_task`, command
  `pcl context pack --task T-0002 --json`, `routing_scope = target`, and an
  explicit Task binding.

### Repository dogfood

Both commands exited 0 and selected current Task `T-0110`:

```text
PYTHONPATH=src python -m pcl --root . next --target T-0110 --json
PYTHONPATH=src python -m pcl --root . next --target G-0054 --json
```

The returned command was `pcl context pack --task T-0110 --json`; no older Goal
was selected.

## Result

The first slice satisfies `TC-0120` through `TC-0123`. It harnesses target
identity, ambiguity, safety gates, and output contracts without prescribing an
LLM reasoning procedure. Skill prose removal remains a separate follow-up and
must be limited to lines with a proven one-to-one runtime replacement.
