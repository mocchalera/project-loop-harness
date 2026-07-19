<!-- project-loop-harness:start -->
## Project Loop Harness

Claude Code should use `pcl` as the only state mutation interface for `.project-loop`.

Before acting:

1. Read `pcl.yaml`.
2. Run `pcl loop status` or `pcl next` when the next action is unclear.
3. Do not read, parse, or hand-edit generated dashboard HTML; it is a human-only view.
4. Use `pcl` JSON commands, reports, evidence paths, or `dashboard-data.json` for machine context.
5. Do not write raw SQL against `.project-loop/project.db`.
6. Let project-local instructions, source files, and current system state govern over general guidance.
7. Before consequential mutation, identify the accepted outcome, proof boundary, and authority envelope.
8. Load only the context and Skills relevant to the current unresolved decision.
9. Use `pcl story` and `pcl test` for behavior-facing test-first work.
10. Preserve evidence paths for claims of completion.
11. Record repeated environment failures with `pcl gap add`; candidate lessons require human promotion approval through `pcl gap promote` and separate application to their durable owner.
<!-- project-loop-harness:end -->
