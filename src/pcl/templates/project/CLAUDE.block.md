<!-- project-loop-harness:start -->
## Project Loop Harness

Claude Code should use `pcl` as the only state mutation interface for `.project-loop`.

Before acting:

1. Read `pcl.yaml`.
2. Run `pcl loop status` or `pcl next` when the next action is unclear.
3. Do not hand-edit generated dashboard HTML.
4. Do not write raw SQL against `.project-loop/project.db`.
5. Use `pcl story` and `pcl test` for behavior-facing test-first work.
6. Preserve evidence paths for claims of completion.
<!-- project-loop-harness:end -->
