# Project Loop Harness v0.5.0: 3-minute adoption demo

This demo shows the product's core promise in one isolated run:

```text
init → literal intent → copied Evidence → guarded verification
     → COMPLETED_VERIFIED → Japanese dashboard → idle
```

It installs the published PyPI package at exactly `0.5.0`. It does not use the
checkout's source code or installed `pcl` command.

![Japanese completion dashboard](../../docs/assets/v0.5.0-demo/dashboard-ja.png)

## Run it

Requirements: `python3`, `git`, and network access to PyPI. No project
dependency is added.

```bash
cd examples/v0.5.0-adoption-demo
./run-demo.sh --keep
```

Open the final `DASHBOARD=...` path in a browser. Use `--paced` for a narrated
run. Without `--keep`, the script removes only the marker-protected temporary
directory it created.

The script deliberately does not call `story approve`, create an approved
human Verification, edit SQLite, or edit generated HTML. The Direct route uses
a guarded completion packet instead: explicit acceptance output is copied and
hash-pinned as Evidence, the allowlisted finish check runs, strict validation
passes, and the Goal closes against the goal-bound packet.

## 3-minute narration

| Time | Screen | Say |
| --- | --- | --- |
| 0:00 | Exact PyPI install and `pcl 0.5.0` | “This is the public package in a new virtual environment.” |
| 0:25 | `init --dry-run`, then `init` and `doctor` | “Adoption is inspect-first and local-only.” |
| 0:55 | `pcl start` JSON | “The operator's intent is preserved literally as a Goal and Task.” |
| 1:15 | One acceptance test | “The result is checked by a reproducible project command.” |
| 1:40 | `evidence add --copy` JSON | “The output is copied, hashed, and linked to the Task.” |
| 2:00 | `finish --emit-packet` | “Guarded checks and strict validation produce `COMPLETED_VERIFIED`; no human approval is fabricated.” |
| 2:30 | Goal close, Japanese render, `next: idle` | “State, proof, handoff, and stop condition agree; the dashboard is only the human view.” |

See [CHECKPOINTS.md](CHECKPOINTS.md) for the exact pass criteria and
[RECORDING.md](RECORDING.md) for capture commands.

## Safety boundary

- All writes happen under a fresh `mktemp` directory.
- Cleanup requires both the expected path prefix and an ownership marker.
- A failure keeps the workspace for diagnosis.
- The source checkout's `.claude`, `.project-loop`, and `pcl.yaml` are not
  modified.
- The disposable target's generated `pcl.yaml` receives one local finish-check
  setting; it is baseline-committed before the demonstrated intent starts.
- There is no push, release, external post, raw SQL, migration, telemetry, or
  provider execution.
