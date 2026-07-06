# Task 0092: Idempotent Same-State Transitions (v0.2.2, F1)

Source: first external-project agent dogfood feedback
(`docs/feedback/2026-07-06-ax1-moc1-agent-feedback.md`, item F1).
`pcl feature status F-0001 --status passing` exits 2 when the feature
is already passing. For scripting agents a same-state request is a
satisfied postcondition, not an input error; exit 2 forces every
caller to pre-read state or wrap errors. No migration, no new
dependency.

## Behavior change (all four sites)

Same-state transition requests become successful no-ops:

- `pcl feature status <id> --status <current>` (`commands.py`
  `set_feature_status`)
- `pcl goal complete` / goal lifecycle same-state (`lifecycle.py`,
  the "Goal ... is already ..." site)
- `pcl test <verb>` when the test case is already in the requested
  terminal state (`stories.py`, the "Test case ... is already ..."
  site)
- `pcl task status <id> <current>` (`tasks.py`, the "Task ... is
  already ..." site)

No-op semantics (identical across all four):

- Exit code 0; JSON gains `"changed": false` plus the current status.
- NOTHING is recorded: no status update, no inline evidence row, no
  event append. A no-op that logs is not a no-op — repeated agent
  retries must not inflate the audit trail.
- Human-readable output states plainly that the entity was already in
  the requested state (e.g. `Feature F-0001 already passing; no
  change recorded.`).
- Supplied `--evidence` / `--reason` text on a no-op is NOT recorded;
  the response must make that explicit (e.g.
  `"evidence_recorded": false`) so callers do not believe evidence
  was attached. Attaching fresh evidence to an already-terminal state
  (re-verification) is out of scope here and belongs to the evidence
  entry-path design.

Changed transitions additionally gain `"changed": true` (additive
JSON field; existing fields untouched).

## What must NOT change

- Invalid TARGET states and disallowed transitions (e.g. rubric or
  guard violations, unknown entities) keep their existing typed
  errors and exit codes. Only the exact same-state case becomes a
  no-op.
- Evidence-backed terminal-state validation invariants are untouched
  (a no-op changes nothing, so nothing new to validate).
- No behavior change for transitions that DO change state, other
  than the additive `changed` field.

## Acceptance Criteria

- For each of the four commands: same-state call → exit 0,
  `changed: false`, row count of events/evidence unchanged (assert
  counts before/after), status unchanged, and repeated invocation is
  stable (call twice more, same result).
- Same-state call with `--evidence "..."` → `evidence_recorded:
  false` in JSON and no evidence row.
- Changed-state calls still record exactly as before and now carry
  `changed: true`.
- Unknown entity / invalid target status still typed errors (regression
  tests kept).
- Docs: `docs/golden-path.md` or command docs note the idempotent
  semantics in one short paragraph.
- `ruff check .` passes; full `python3 -m pytest` passes; `pcl init`
  smoke against a temp dir passes.

## Do Not

- Do not make disallowed transitions succeed.
- Do not append events or evidence on no-ops.
- Do not add a `--force` re-record path (that is evidence-path design
  territory).
- Do not touch schema or raw SQL outside the existing service layer.
