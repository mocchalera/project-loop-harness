# v0.6.0 adoption proof cohort runbook

This runbook operationalizes the frozen protocol in
[`docs/adoption-proof-v0.5.2.md`](adoption-proof-v0.5.2.md) and its
[participant kit](adoption-proof-v0.5.2-participant-kit.md) for one exact
public candidate. It changes no threshold, no schema, and no session step.
If this document ever disagrees with the frozen protocol, the frozen protocol
wins.

## Candidate (frozen)

- Candidate ID: `v0.6.0-pypi`
- Artifact: `project_loop_harness-0.6.0-py3-none-any.whl` from PyPI
- SHA-256: `4857355d108f720feb93497dc17ae53bb9b7502f4549a0f26c1a97cfa655137d`
- Freeze record: `docs/evidence/0248-v060-public-candidate-freeze.md`

The operator hands every participant the same wheel file plus the README.
Installing from a local wheel file (not an unpinned index install) keeps the
observed artifact identical to the frozen hash.

## Five slots

| Slot | ID | Repository family | Status |
| --- | --- | --- | --- |
| 1 | AP-001 | python | open |
| 2 | AP-002 | node | open |
| 3 | AP-003 | mixed | open |
| 4 | AP-004 | python / go / rust / other | open |
| 5 | AP-005 | any remaining family | open |

At least three distinct families must be filled for the diversity gate; slots
4–5 are intentionally flexible so recruitment does not stall on family quotas.

### Slot eligibility checklist (verify before accepting a participant)

- Not the maintainer; has never used `pcl` before (`first_time_user: true`).
- Brings a real repository they already understand — not a demo repo.
- The repository has obvious lint/test commands (for example `pytest` +
  `ruff`, or `npm test` + `npm run lint`). Rationale: healthy setup requires
  configured finish checks, and the 5-minute median is unreachable if the
  participant must first invent project tooling.
- No production secrets, customer data, or destructive task in scope.
- Uses a coding agent they already know (Codex, Claude Code, or similar).
- Can complete one ~30-minute observed session and one ~2-minute day-7 reply.

## Bounded task rule

Each participant chooses one bounded, reversible change that normally takes
under 20 minutes with their agent: a doc fix, small refactor, comment cleanup,
test addition, or similar local-only edit. Reject tasks that deploy, publish,
message anyone, delete data, or touch credentials. The observer confirms the
task is bounded before the agent prompt is submitted and records nothing about
the task's content beyond the coarse outcome enums.

## Session flow (per frozen kit)

1. Operator agrees the session window; screen share starts only after consent.
2. Participant installs the frozen wheel with `pipx`/`uv tool`; wall-clock
   install start is noted.
3. Participant runs `pcl init --dry-run --json`, inspects, runs `pcl init`,
   then configures real checks until `pcl doctor --strict` is clean; healthy
   setup time is noted.
4. Participant pastes the README outcome prompt into their coding agent.
5. After the prompt is submitted, the observer may explain the study or safety
   boundary only. Supplying a routine command, editing `pcl.yaml`, or repairing
   loop state counts as a maintainer intervention and is counted, never hidden.
6. Session stops at a completion packet, a genuine human decision, or 30
   minutes. Stop immediately on withdrawal, potential credential/customer/
   private-URL exposure, destructive drift, a crossed human gate, or a
   repeating failure with no safe next step.

## Observation record validation

Draft one sanitized JSON record per participant using the
`adoption-observation/v1` contract exactly as specified in the frozen protocol
(same fields, enums, pseudonymous IDs `AP-001`–`AP-005`, elapsed seconds).

Validate each draft offline before review:

```bash
python scripts/evaluate_adoption_proof.py --records-dir <draft-dir>
```

- A single draft record should yield exit 2 if malformed or exit 1 with status
  `incomplete` if valid (a cohort of one can never pass). Exit 2 on a draft
  means fix the record; it must never be "interpreted into" validity.
- Records that reach healthy setup but not completion keep
  `install_to_healthy_seconds`, set `verified_completion: false`,
  `completion_seconds: null`, an incomplete outcome enum, and a non-none stop
  reason. Record `not reached`; never invent durations.
- Approved records are stored under `docs/evidence/adoption-proof-v0.5.2/`
  (the directory does not exist yet; create it with the first approved record).

## Seven-day reuse follow-up

Exactly one question per participant, seven days after their session: did you
voluntarily start another `pcl` goal without study prompting? Record `true`,
`false`, or `null` when unknown. A reminder-driven or maintainer-operated
session is not reuse. Update the participant's record's
`voluntary_reuse_day_7` field; do not create side lists.

## Denominator handling

Every gate reports `observed` and `required`; the evaluator prints all of them
on every run, including misses. Rules:

- All five records are required for any gate to pass; four valid records is an
  incomplete cohort, not an 80% result.
- If any participant never reaches healthy setup, the median gate fails and
  stays failed — that is a valid outcome, not a data-quality problem to repair.
- Until all five `voluntary_reuse_day_7` values are non-null, status remains
  `incomplete` even if counts look decisive.
- Missing thresholds are reported as misses in the result report; they are
  never re-baselined after observation.

## Offline evaluation of the final cohort

```bash
python scripts/evaluate_adoption_proof.py \
  --records-dir docs/evidence/adoption-proof-v0.5.2
```

Exit 0 = every frozen gate passes; exit 1 = valid evidence, incomplete or a
threshold miss; exit 2 = invalid evidence. The evaluator refuses mixed
candidate IDs/hashes and duplicate participants. Run it twice and diff outputs
before publishing; output is deterministic by design.

## Result report structure

Publish one report that separates, verbatim per the frozen protocol: observed
participant outcomes, maintainer inference, internal dogfood evidence, and
unknowns/sample limits. Every miss and denominator appears explicitly. The
final roadmap decision — continue, change the onboarding path, or stop /
deprioritize the adoption claim — links to this evidence and is recorded by a
human, not inferred by the evaluator.

## Human decisions required before recruitment begins

Only these; nothing broader:

1. Approve this candidate freeze (`v0.6.0-pypi`, SHA-256 above) or name a
   different artifact to freeze instead.
2. Approve the invitation channel and the specific five invitees (the kit's
   invitation draft text is ready; sending it is a human action).
3. Name the observer for sessions where the maintainer is also the operator,
   so intervention counting stays honest.
4. Confirm who owns the day-7 follow-up messages and when the records
   directory becomes reviewable.
