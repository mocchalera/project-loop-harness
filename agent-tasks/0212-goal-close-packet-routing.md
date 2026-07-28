# 0212: Goal completion-packet close routing

- **Status:** Completed and real-project verified
- **Milestone:** P1 real-use friction follow-up
- **Priority:** P1
- **Size:** S
- **Dependency:** 0193 target-bound routing; P1 finish progress/compact output dogfood
- **Project Loop:** Goal `G-0074`, Task `T-0152`, Feature `F-0081`
- **Stories:** `US-0084`, `US-0085`
- **Tests:** `TC-0193`–`TC-0198`
- **DB schema:** remains 8

## Problem

Real-project dogfood produced a valid, exact-goal
`COMPLETED_WITH_RISK` packet as Evidence `E-0666`. The Goal remained open, as
required by the existing separation between `finish` and `goal close`.
Immediately afterward, however:

```text
pcl next --target G-0073 --json
```

recommended the same long-running `pcl finish --emit-packet --goal G-0073`
again instead of the already-authorized close command:

```text
pcl goal close G-0073 \
  --summary 'Summarize completed goal' \
  --evidence-id E-0666
```

This can repeat more than ten minutes of verification even though exact,
compatible terminal proof already exists.

The closeout also showed that `pcl goal close --help` renders generic
`--evidence-id EVIDENCE_ID` and `--verification VERIFICATION` arguments. It
does not tell the operator that direct-route closure expects an `E-XXXX`
completion-packet Evidence ID while workflow closure expects an approved
`V-XXXX` Verification ID.

## Decision

Add a read-only, fail-closed completion-packet route before the existing direct
Goal finish route.

For an open direct-route Goal whose child Task, Feature, Story, and Test work is
already terminal:

1. retain exact-target timeout/recovery routing at higher precedence;
2. inspect only the newest completion-packet Evidence linked to that exact
   Goal;
3. require healthy, non-superseded Evidence;
4. require a valid `completion-packet/v1` whose target is that Goal;
5. require `COMPLETED_VERIFIED` or low-risk `COMPLETED_WITH_RISK`;
6. require the packet repository identity to equal the repository identity a
   finish would capture now;
7. return `close_goal` with the exact packet Evidence ID;
8. otherwise retain the existing `emit_completion_packet` action.

The route does not close the Goal automatically. It only returns the exact
agent-safe command that the direct implementation loop already authorizes.

## Guided-action contract

The new direct close recommendation uses the existing guided-action envelope:

```json
{
  "type": "close_goal",
  "command": "pcl goal close G-0001 --summary 'Summarize completed goal' --evidence-id E-0001",
  "target": {
    "id": "G-0001",
    "status": "open",
    "completion_packet_evidence_id": "E-0001",
    "packet_outcome": "COMPLETED_VERIFIED"
  },
  "blocking": false,
  "requires_human": false,
  "safe_to_run": true,
  "run_policy": "agent_safe"
}
```

Explicit `next --target G-XXXX` retains its current `target_binding` and
`routing_scope`. Unbound single-Goal routing may return the same action.
Cross-Goal ambiguity, project-wide safety gates, workflow-backed Goal routing,
and terminal-target behavior remain unchanged.

## Packet resolution

Resolution is fail-closed:

- never use a Task-bound packet to close a Goal;
- never fall back to an older packet when the newest exact-goal packet is
  invalid, unreadable, unhealthy, superseded, incomplete, high-risk, or stale;
- never infer a different Goal from packet contents;
- never hide exact-target timeout recovery behind an older completed packet;
- never change packet health, lifecycle proof, or repository identity rules.

The finish repository snapshot implementation becomes a small shared read-only
service used by both finish and routing. Do not duplicate Git diff hashing in
`action_routing.py`, and do not call the full finish planner merely to resolve a
route.

## CLI proof-ID clarity

`pcl goal close --help` becomes explicit:

```text
--evidence-id E-XXXX
    Completed goal-bound packet Evidence ID for a direct-route Goal.

--verification V-XXXX
    Approved Verification ID from a Workflow Run for this Goal.
```

The legacy `--evidence` compatibility argument is still accepted and described
as non-terminal raw inline Evidence. Parser destinations, mutual exclusion,
exit codes, validation, state mutation, events, and JSON result shape remain
unchanged.

## Fail-first Tests

| Test | Story | Contract |
| --- | --- | --- |
| `TC-0193` | `US-0084` | a current healthy completed exact-goal packet routes to agent-safe `close_goal` |
| `TC-0194` | `US-0084` | missing, unreadable, unhealthy, wrong-target, incomplete, or high-risk proof never closes |
| `TC-0195` | `US-0084` | repository drift makes a completed packet non-reusable and routes to fresh finish |
| `TC-0196` | `US-0084` | exact-target timeout recovery retains precedence over older completed proof |
| `TC-0197` | `US-0084` | no-packet `emit_completion_packet` output and unbound behavior remain compatible |
| `TC-0198` | `US-0085` | help exposes `E-XXXX` / `V-XXXX` types without runtime contract drift |

The first RED must reproduce the observed duplicate-finish recommendation from
a real public-command fixture. Tests use fast deterministic finish commands;
they do not use multi-minute sleeps.

## Candidate files

- `src/pcl/action_routing.py`
- `src/pcl/finish_execution.py`
- a small shared finish-repository snapshot module
- `src/pcl/parser_entities.py`
- `tests/test_next_actions.py`
- `tests/test_field_feedback_0165.py`
- focused parser/help tests if existing coverage cannot express `TC-0198`

## Verification

```text
PYTHONPATH=src pytest <targeted routing and parser tests>
PYTHONPATH=src pytest
PYTHONPATH=src ruff check .
PYTHONPATH=src python -m pcl --root . validate --strict --json
PYTHONPATH=src python -m pcl --root . render --json
```

Dogfood uses a fresh explicitly bound Goal and short deterministic finish
check. It must prove:

- `emit_completion_packet` before packet creation;
- `close_goal` with the exact Evidence ID after packet creation;
- no state mutation from either `next` call;
- stale repository proof returns to `emit_completion_packet`;
- executing the recommended close command makes the Goal terminal;
- `next --target` then returns `target_terminal`.

## Stop conditions

Stop and request a new human decision before:

- a database migration or dependency addition;
- packet v2, packet mutation, or relaxed completion-risk acceptance;
- automatic Goal closure inside `finish` or `next`;
- reuse of stale or non-latest packet Evidence;
- weakening timeout recovery, terminal readiness, Evidence health, or
  target-binding checks;
- a public JSON field removal, rename, or exit-semantics change;
- push, PR, publication, telemetry, or external writes.

## Approval boundary

Planning completion means this file, draft Stories, planned Tests, PCL
validation/render, and immutable plan Evidence exist. Implementation starts
only after a human explicitly approves `US-0084`, `US-0085`, and this plan.

## Implementation milestone

- Human approval: Cockpit Ask `ask_8fbed60d3193`
- Implementation commit: `5ba0b1b`
- GREEN Evidence: `E-0675`
- Targeted verification: `53 passed`
- Full verification: `1268 passed, 1 skipped`
- Ruff: passed
- Schema/dependencies: unchanged

The implementation shares both Goal completion-packet eligibility and finish
repository snapshot logic with the existing lifecycle/finish paths. The public
regression covers latest-only routing, unhealthy and high-risk rejection,
repository drift, timeout precedence, no-packet compatibility, typed help, the
recommended close command, and terminal explicit-target routing.

## Real-project dogfood

- Pre-packet route: `emit_completion_packet` for explicit `G-0074`
- Completion packet: `E-0678`, `COMPLETED_WITH_RISK`
- Checks: Ruff and full pytest passed
- Progress: 29 JSONL events, 0 dropped, 30-second heartbeats
- Compact result size: 7,661 bytes
- Post-packet route: agent-safe `close_goal` with exact `E-0678`
- Read-only proof: DB and event checksums unchanged across both `next` calls
- Close result: `G-0074` closed with completion-packet proof
- Terminal route: `target_terminal` for explicit `G-0074`
- Dogfood Evidence bundle: `E-0679`
- Final validate/render Evidence: `E-0680`
