# 0171 actionable finish timeout recovery validation

Date: 2026-07-14

## Scope

- Goal: `G-0032`
- Feature: `F-0033`
- Story: `US-0031`
- Tests: `TC-0094`, `TC-0095`
- Runtime surfaces: `pcl finish --emit-packet`, `pcl next`
- Schema/dependencies: unchanged

## Dogfood reproduction

The preceding repository close-out ran the default command:

```bash
PYTHONPATH=src python -m pcl finish --emit-packet --goal G-0031 --json
```

The full `pytest` finish check exceeded the 120-second default. PCL recorded
the timeout as check Evidence `E-0292` and incomplete packet Evidence `E-0293`,
but the next-action route repeated the same command without a higher timeout.
The agent recovered only by supplying `--timeout 600` manually; checks
`E-0294` and `E-0295` then passed and packet `E-0296` completed the goal.

## Implemented recovery contract

- A timed-out check below the ceiling adds structured `timeout_recovery` data
  to the finish JSON response.
- The response and packet contain the same exact retry command for the same
  target with `--timeout 600 --json`.
- `pcl next --json` reads only the latest valid packet for an active target and
  preserves that command as `agent_safe`.
- A timeout already at 600 seconds has no retry command. The packet and
  `pcl next` point to `pcl evidence show <timed-out-evidence> --json` instead.
- Packet-derived commands are fail-closed: only commands reconstructed exactly
  from the validated target or timed-out Evidence reference are accepted.
- A newer non-timeout packet suppresses an older timeout route.

## Focused verification

```text
PYTHONPATH=src pytest -q tests/test_finish.py tests/test_next_actions.py tests/test_field_feedback_0165.py
46 passed in 11.27s

PYTHONPATH=src python -m ruff check src/pcl/finish_execution.py src/pcl/finish_recovery.py src/pcl/commands.py tests/test_finish.py
All checks passed!
```

The integration fixtures exercise timeout packet creation without sleeping,
then call the public `pcl next` CLI path. They also cover the 600-second ceiling,
ordinary failure compatibility, stale packet suppression, and command
tampering rejection.

## Full verification

```text
PYTHONPATH=src python -m ruff check .
All checks passed!

git diff --check
exit 0

PYTHONPATH=src pytest -q
997 passed, 1 skipped in 230.53s
```

## Residual risk

- The first retry deliberately uses the guarded 600-second ceiling rather than
  estimating project-specific duration. Checks that legitimately need longer
  require configuration or suite decomposition outside this slice.
- Timeout recovery is surfaced, not auto-executed. The supervising agent must
  still run the returned safe command.
- Corrupt, invalid, terminal-target, or non-canonical packet commands are
  ignored by `pcl next` and fall through to existing routing.
