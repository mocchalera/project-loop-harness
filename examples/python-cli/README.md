# Python CLI Example

This is a seed `pcl.yaml` for a Python command-line project.

Try it in a scratch directory:

```bash
cp -R examples/python-cli /tmp/pcl-python-cli-example
pcl init --target /tmp/pcl-python-cli-example
pcl doctor --root /tmp/pcl-python-cli-example
pcl validate --root /tmp/pcl-python-cli-example --strict --json
pcl next --root /tmp/pcl-python-cli-example --json
pcl render --root /tmp/pcl-python-cli-example --json
```

Then start a real loop:

```bash
pcl goal create --root /tmp/pcl-python-cli-example --title "Reach basic feature coverage"
pcl loop run --root /tmp/pcl-python-cli-example feature_coverage --goal G-0001
pcl next --root /tmp/pcl-python-cli-example --explain
```

Do not commit the generated `.project-loop/` directory from scratch runs. If strict validation fails, use `docs/recovery-playbook.md` from this repository.
