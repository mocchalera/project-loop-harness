# 0171: Actionable finish timeout recovery

- **Status:** Complete
- **Milestone:** v0.5.0 Adoption / Distribution
- **Priority:** P0
- **Size:** S
- **Dependencies:** 0135, 0165
- **DB schema:** no change
- **Human approval:** Story US-0031 approved in Cockpit on 2026-07-14

## User problem

`pcl finish --emit-packet` uses a 120-second per-check default. A legitimate
project suite can exceed that bound, leaving an incomplete packet while
`pcl next` recommends the same command and therefore the same ineffective
timeout. The agent can recover only if a human supplies the missing CLI flag.

## Product outcome

A timed-out finish result exposes one exact, bounded retry command for the same
target, and `pcl next` preserves that route. If the 600-second safety ceiling
also times out, PCL routes the agent to the captured Evidence instead of
recommending the same retry again.

## Scope

1. Detect `timed_out` completion checks separately from ordinary failures.
2. Add structured timeout-recovery details to the `pcl finish` result.
3. Put the exact bounded retry or diagnostic command in the completion packet.
4. Prefer the latest active target's timeout recovery in `pcl next`.
5. Keep retry execution explicit and guarded.

## Invariants

- PCL does not auto-run the retry or change configured finish checks.
- The retry timeout never exceeds the guarded executor's 600-second ceiling.
- A timeout remains `INCOMPLETE_VALIDATION`; no completion claim or terminal
  transition is invented.
- The completion packet remains valid `completion-packet/v1`.
- Superseded timeout packets do not override a newer valid packet for the same
  target.
- No schema migration, dependency, network request, or external write.

## Acceptance

1. A timeout below the ceiling returns an exact retry command with
   `--timeout 600 --json` for the same target.
2. The packet and subsequent `pcl next --json` expose the same command as an
   agent-safe action.
3. A timeout at 600 seconds returns no repeat retry and routes to the timed-out
   check Evidence for diagnosis.
4. Ordinary failed checks preserve their existing next action.
5. A newer valid non-timeout packet suppresses stale timeout recovery.
6. Focused tests, `ruff check .`, full `pytest`, strict validation, rendering,
   and real-repository finish verification pass.

## Non-goals

- Automatically estimating an unbounded test duration.
- Automatically editing `pcl.yaml` or splitting project test suites.
- Retrying failed checks without an explicit agent command.
- Changing completion-packet/v1 fields.
