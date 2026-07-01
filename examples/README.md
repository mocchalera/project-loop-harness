# Example Projects

These examples are seed project roots. They intentionally do not contain `.project-loop/` state.

Copy one example to a scratch directory, then initialize Project Loop Harness there:

```bash
cp -R examples/python-cli /tmp/pcl-python-cli-example
pcl init --target /tmp/pcl-python-cli-example
pcl validate --root /tmp/pcl-python-cli-example --strict --json
pcl next --root /tmp/pcl-python-cli-example --json
pcl render --root /tmp/pcl-python-cli-example --json
```

Use the same pattern for `examples/nextjs`.

The bundled `pcl.yaml` is preserved by `pcl init` unless `--force` is used. That lets each example show a realistic project policy while the CLI adds local state, workflow templates, agent instructions, and dashboard output.

For the full operator path, read `docs/golden-path.md`. If validation fails, follow `docs/recovery-playbook.md`.

For using Project Loop Harness in a real new repository, read
`docs/adoption-guide.md` before the golden path. It explains distribution
choices, which initialized files to commit, and the first prompt to give a
coding agent.
