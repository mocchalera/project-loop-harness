# 0164 guided dashboard red tests

Date: 2026-07-13

Command:

```bash
PYTHONPATH=src pytest -q \
  tests/test_dashboard.py::test_dashboard_operator_summary_precedes_advanced_details_in_japanese \
  tests/test_dashboard.py::test_dashboard_operator_summary_localizes_human_gate_without_english_reason \
  tests/test_dashboard.py::test_dashboard_operator_done_only_reports_evidence_backed_transitions \
  tests/test_codex_plugin.py::test_project_control_loop_skill_is_synced_across_packages
```

Observed result: **4 failed**.

- Three dashboard tests failed because `id="operator-summary"` and the advanced
  details disclosure do not exist yet.
- The Skill parity contract test failed because the four review moments and
  host-neutral presentation rule do not exist yet.

The existing init, Story, Test, Evidence, and render setup steps completed. The
failures therefore reproduce the missing 0164 behavior rather than an unrelated
fixture or environment problem.

