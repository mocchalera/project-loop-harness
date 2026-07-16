# v0.5.2 Adoption Proof participant kit

This is the one-page handoff for a 30-minute first-use session. It is not a
sales demo. The participant uses a real, non-sensitive repository and chooses a
small reversible task they already understand.

## Invitation draft

> Would you try a 30-minute first-use study of Project Loop Harness, a local
> tool that helps coding agents prove completion and preserve the next step?
> You will use your own coding agent on a small reversible change. We record
> coarse timings and outcomes only—never your name, repository URL, source code,
> credentials, or full transcript. You can stop at any time, and no result is
> presented as your endorsement.

The operator may copy or adapt this text. This repository does not send it.

## Before the session

The operator:

1. builds or obtains one candidate wheel;
2. records a non-personal candidate ID and its SHA-256;
3. uses that exact artifact for all five participants;
4. confirms the repository contains no production secret or destructive task;
5. starts screen sharing or observation only after the participant agrees.

Example candidate preparation:

```bash
python -m build --wheel --outdir /tmp/pcl-v052-candidate
shasum -a 256 /tmp/pcl-v052-candidate/project_loop_harness-*.whl
```

Candidate creation is internal preparation. Sending a wheel, recruiting a
participant, or publishing a candidate requires a separate human action.

## Participant path

The participant receives the candidate wheel and the repository README. They:

1. install with `pipx install /path/to/candidate.whl` or
   `uv tool install /path/to/candidate.whl`;
2. run `pcl init --dry-run --json` and inspect the proposed writes;
3. run `pcl init`, then `pcl doctor --strict`;
4. paste the README outcome prompt into their normal coding agent;
5. choose one bounded, reversible change;
6. stop at a completion packet, a genuine human decision, or 30 minutes.

The observer may explain the study and safety boundary. After the agent prompt
is submitted, supplying a routine command, editing `pcl.yaml`, or repairing loop
state counts as a maintainer intervention. Never hide the intervention to make
the session look successful.

## Stop immediately when

- the participant withdraws;
- a credential, customer record, private URL, or production data may be exposed;
- the requested change becomes destructive or externally visible;
- the agent crosses a declared human gate;
- the same failure repeats and the safe next step is unclear.

## What the observer records

Create one exact `adoption-observation/v1` JSON file using the contract in
`docs/adoption-proof-v0.5.2.md`. Use only pseudonymous IDs `AP-001` through
`AP-005`, coarse repository family, elapsed seconds, result enums, counts, and
confusion codes.

Do not place names, email addresses, repository URLs, source code, credentials,
screenshots, raw prompts, or full transcripts in the JSON. A short participant
quote may be kept separately only when the participant explicitly approves its
exact sanitized wording; it is qualitative context and never changes a gate.

## Seven-day follow-up

Ask only whether the participant voluntarily started another `pcl` goal without
study prompting. Record `true`, `false`, or `null` when unknown. Do not count a
reminder-driven or maintainer-operated session as voluntary reuse.

## Evaluate

```bash
python scripts/evaluate_adoption_proof.py \
  --records-dir docs/evidence/adoption-proof-v0.5.2
```

- exit 0: every frozen gate passes;
- exit 1: records are valid but incomplete or a threshold misses;
- exit 2: a record is invalid, duplicated, or mixes candidate artifacts.

The JSON result is the calculation artifact, not proof that the observer's
input was truthful. Preserve approved observation evidence separately.
