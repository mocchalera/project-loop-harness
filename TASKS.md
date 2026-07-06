# Implementation Task Index

Give these tasks to coding agents in this order:

1. `agent-tasks/0001-hardening-cli.md`
2. `agent-tasks/0002-db-migrations.md`
3. `agent-tasks/0003-workflow-runner.md`
4. `agent-tasks/0004-dashboard-renderer.md`
5. `agent-tasks/0005-agent-integration.md`
6. `agent-tasks/0006-codex-plugin.md`
7. `agent-tasks/0007-mcp-server.md`
8. `agent-tasks/0008-loop-lifecycle.md`
9. `agent-tasks/0009-defect-lifecycle.md`
10. `agent-tasks/0010-reporting-evidence.md`
11. `agent-tasks/0011-validation-invariants.md`
12. `agent-tasks/0012-audit-log-integrity.md`
13. `agent-tasks/0013-validation-diagnostics.md`
14. `agent-tasks/0014-escalation-lifecycle.md`
15. `agent-tasks/0015-decision-lifecycle.md`
16. `agent-tasks/0016-escalation-decision-linkage.md`
17. `agent-tasks/0017-next-action-guided-loop.md`
18. `agent-tasks/0018-readme-golden-path.md`
19. `agent-tasks/0019-recovery-playbook.md`
20. `agent-tasks/0020-example-project-refresh.md`
21. `agent-tasks/0021-agent-adapter-contract.md`
22. `agent-tasks/0022-agent-output-validation.md`
23. `agent-tasks/0023-codex-exec-adapter-hardening.md`
24. `agent-tasks/0024-claude-manual-adapter-hardening.md`
25. `agent-tasks/0025-generic-shell-adapter.md`
26. `agent-tasks/0026-agent-job-evidence-ingestion.md`
27. `agent-tasks/0027-dashboard-data-contract.md`
28. `agent-tasks/0028-dashboard-evidence-navigation.md`
29. `agent-tasks/0029-dashboard-risk-and-blockers.md`
30. `agent-tasks/0030-distribution-readiness.md`
31. `agent-tasks/0031-workflow-proposal-mode.md`
32. `agent-tasks/0032-workflow-proposal-review.md`
33. `agent-tasks/0033-workflow-verifier.md`
34. `agent-tasks/0034-limited-execution-sandbox.md`
35. `agent-tasks/0035-automatic-workflow-executor.md`
36. `agent-tasks/0036-executor-dogfood-workflow.md`
37. `agent-tasks/0037-executor-retry-resume.md`
38. `agent-tasks/0038-story-test-lifecycle.md`
39. `agent-tasks/0039-workflow-yaml-rule-expressions.md`
40. `agent-tasks/0040-test-case-evidence-validation.md`
41. `agent-tasks/0041-feature-inspection-commands.md`
42. `agent-tasks/0042-report-coverage-context.md`
43. `agent-tasks/0043-feature-report.md`
44. `agent-tasks/0044-complete-csv-export.md`
45. `agent-tasks/0045-filtered-job-inspection.md`
46. `agent-tasks/0046-feature-status-lifecycle.md`
47. `agent-tasks/0047-feature-coverage-next-action.md`
48. `agent-tasks/0048-migration-status-command.md`
49. `agent-tasks/0049-render-json-artifact-paths.md`
50. `agent-tasks/0050-codex-plugin-package-inventory.md`
51. `agent-tasks/0051-mcp-render-artifact-paths.md`
52. `agent-tasks/0052-lifecycle-failure-job-cleanup.md`
53. `agent-tasks/0053-prompt-job-json-handoff.md`
54. `agent-tasks/0054-human-queue-linkage-cli.md`
55. `agent-tasks/0055-workflow-proposal-list-filter.md`
56. `agent-tasks/0056-sandbox-noop-execution-guard.md`
57. `agent-tasks/0057-executor-no-executable-step-guard.md`
58. `agent-tasks/0058-dogfood-usability-hardening.md`
59. `agent-tasks/0059-checkpoint-review-guidance.md`
60. `agent-tasks/0060-pypi-trusted-publishing.md`
61. `agent-tasks/0061-context-pack-v1.md`
62. `agent-tasks/0062-task-backlog-entity.md`
63. `agent-tasks/0063-structured-verification-rubric.md`
64. `agent-tasks/0064-task-loop-integration.md`
65. `agent-tasks/0065-dashboard-human-decisions.md`
66. `agent-tasks/0066-agent-registry-lease.md`
67. `agent-tasks/0067-context-pack-improvements.md`
68. `agent-tasks/0068-trust-hardening.md`
69. `agent-tasks/0069-explainable-code-context-v0.md`
70. `agent-tasks/0070-human-decision-cockpit.md`
71. `agent-tasks/0071-dogfood-impact-precision.md`
72. `agent-tasks/0072-sensitive-omission.md`
73. `agent-tasks/0073-code-context-module-split.md`
74. `agent-tasks/0074-search-snapshot-consistency.md`
75. `agent-tasks/0075-diff-source-modes.md`
76. `agent-tasks/0076-schema-version-integrity.md`
77. `agent-tasks/0077-index-output-budget-and-impact-noise.md`
78. `agent-tasks/0078-context-pack-code-context-bridge.md`
79. `agent-tasks/0079-receipt-human-summary.md`
80. `agent-tasks/0080-retrieval-eval-gate.md`
81. `agent-tasks/0081-diff-modes-completion.md`
82. `agent-tasks/0082-receipt-relevance-and-age.md`
83. `agent-tasks/0083-required-section-invariant.md`
84. `agent-tasks/0084-source-commands-honesty.md`
85. `agent-tasks/0085-distribution-source-completeness.md` (retroactive record; implemented in `204a857`)
86. `agent-tasks/0086-command-surface-alignment.md` (retroactive record; implemented in `204a857`)
87. `agent-tasks/0087-verification-suggestion-ids.md` (v0.2.0)
88. `agent-tasks/0088-verification-feedback.md` (v0.2.0, migration 005 — approved)
89. `agent-tasks/0091-refresh-command-scope-fidelity.md` (retroactive record; implemented in `204a857`; numbered 0091 per the v0.1.12 review agenda)

Tasks 0089 (dogfood-to-fixture propose) and 0090 (eval baseline
record/compare) are scheduled for v0.2.1; their specs are filed after
the v0.2.0 release, per `docs/v0.2.0-plan.md`.

Do not start with MCP. Do not start with a hosted UI. The CLI/runtime must become reliable first.
