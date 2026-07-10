# 0140c: Fail-open finish check guard

- **Status:** Approved v0.4.0 RC2 release blocker
- **Milestone:** v0.4.0 Integrity Gate
- **Priority:** P0
- **Estimated size:** S-M
- **Dependencies:** 0140
- **Parallel-safe with:** 0140a, 0140b

## Problem

Dogfood used a configured check with the wrong fixed implementation path and a
shell fallback such as `|| echo`. The target was not inspected, but the command
exited zero and could be recorded as a passed completion check.

An allowlisted command is not trustworthy merely because its final shell exit
status is zero when the command explicitly converts a missing target or failed
check into success.

## Goal

Prevent obvious fail-open check commands from being executed or counted as
completion proof.

## Scope: Phase A

- Detect bounded, explicit fail-open forms including:
  - `|| true`;
  - `|| echo ...`;
  - `|| printf ...`;
  - equivalent simple target-missing success fallbacks.
- Mark the command `safe_to_run: false` with stable
  `blocked_reason: fail_open_check_command` before execution.
- Preserve empty-command skip behavior and compatible safe static commands.
- Prove at the finish integration layer that a missing fixed path plus fallback
  cannot produce a completed packet.

Structured `checks.*`, required path/environment declarations, and `--var`
context are Phase B and not part of the v0.4.0 blocker.

## Invariants

- Blocked commands are never executed.
- Existing command allowlist, cap, redaction, and race-detection behavior is
  preserved.
- No schema migration, dependency, or project-specific path is added to core.
- Detection is intentionally conservative and documents its recognized shell
  patterns; it does not claim to be a general shell parser.

## Acceptance criteria

- Unit tests cover each recognized fail-open pattern and nearby safe commands.
- Finish tests prove a missing path with `|| echo` cannot yield
  `COMPLETED_VERIFIED`.
- The public blocked reason is deterministic in JSON and text surfaces.
- Targeted sandbox/finish tests and `ruff check` pass.
