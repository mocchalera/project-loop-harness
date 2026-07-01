# Next.js Example

This is a seed `pcl.yaml` for a Next.js application.

Try it in a scratch directory:

```bash
cp -R examples/nextjs /tmp/pcl-nextjs-example
pcl init --target /tmp/pcl-nextjs-example
pcl doctor --root /tmp/pcl-nextjs-example
pcl validate --root /tmp/pcl-nextjs-example --strict --json
pcl next --root /tmp/pcl-nextjs-example --json
pcl render --root /tmp/pcl-nextjs-example --json
```

Then start a real loop:

```bash
pcl goal create --root /tmp/pcl-nextjs-example --title "Reach basic feature coverage"
pcl loop run --root /tmp/pcl-nextjs-example feature_coverage --goal G-0001
pcl next --root /tmp/pcl-nextjs-example --explain
```

Package-manager commands in `pcl.yaml` are examples for real projects. The Project Loop Harness smoke path does not run `pnpm install`, `pnpm build`, or external services. If strict validation fails, use `docs/recovery-playbook.md` from this repository.
