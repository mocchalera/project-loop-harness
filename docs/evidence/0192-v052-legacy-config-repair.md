# v0.5.2 legacy config repair evidence

Date: 2026-07-16

## Scope

This slice closes the local upgrade blocker found in the v0.5.2 verification
matrix: a Node project initialized by public v0.5.1 retains empty quoted command
placeholders after installing the candidate, so `pcl doctor --strict` fails.

The new explicit route is:

```bash
pcl init --repair-config --dry-run --json
pcl init --repair-config
pcl doctor --strict
```

It normalizes only direct empty quoted values for the six legacy template keys
under `commands`. It does not overwrite `pcl.yaml`, is mutually exclusive with
`--force`, preserves comments and non-empty values, and is idempotent. Existing
database rows and JSONL history remain intact; the applied repair appends one
required `project_config_repaired` audit event.

## Test-first acceptance

- Task: `T-0106`
- Feature: `F-0053`
- Story: `US-0051`
- Test: `TC-0116`
- Targeted init tests: `29 passed`
- Init, distribution, adoption docs, and evaluator tests: `43 passed`
- Full suite: `1079 passed, 1 skipped in 307.70s`
- Ruff: `All checks passed!`
- `git diff --check`: passed
- README: 195 lines

## Real public-v0.5.1 upgrade rehearsal

The existing rehearsal target was originally initialized by the public
`project-loop-harness==0.5.1` package and contained:

- Goal `G-0001`;
- Task `T-0001`, titled `Preserve this v0.5.1 task`;
- `test: "npm run test"` plus five unused command values written as `""`.

A wheel built from the working tree was force-installed over that isolated
v0.5.1 environment:

```text
/tmp/pcl-v052-repair-dist/project_loop_harness-0.5.1-py3-none-any.whl
sha256: 506be60cc12142f6305d4d1caae544071be2e531d22c55699266617214518278
```

The artifact still carries the repository's current `0.5.1` metadata because
version bump and release are outside this slice.

Before and after `--dry-run`, hashes were identical:

```text
pcl.yaml:                    6d2aed021183f1780747a6961057b6b0b5e4dc9ef49d71a1f428d1360021e12d
.project-loop/events.jsonl:  89414ece5d109838f19a98e079505c331de0350e7ec77c29972b7c921566963e
.project-loop/project.db:    b03b50034d7bc2fd3cbb18f679ccc605a47add28d290f327ea23ebc41b84ee62
```

The dry-run reported exactly these command repairs:

```text
install, lint, typecheck, e2e, build
```

After applying the repair:

- the five empty placeholders became `null`;
- `test: "npm run test"` remained unchanged;
- `pcl doctor --strict --json` returned `ok: true` with zero findings;
- `pcl validate --strict --json` returned `ok: true` with zero findings;
- `pcl audit check --json` returned `status: clean`, with 12 SQLite events,
  12 JSONL events, and zero anomalies;
- `G-0001` and `T-0001` remained present and unchanged;
- a second repair returned `event_appended: false` and
  `repaired_config_commands: []`;
- JSONL contained exactly one `project_config_repaired` event.

## Distribution checks

```text
python -m build --wheel --outdir /tmp/pcl-v052-repair-dist  PASS
python -m twine check <candidate-wheel>                     PASS
```

No schema migration, dependency, telemetry, provider call, external write,
version bump, push, or release was performed.
