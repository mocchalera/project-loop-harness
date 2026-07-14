# v0.5.0 first-use feedback study

## Purpose and boundary

This is a moderated, qualitative study for three first-time users. It tests
whether v0.5.0 communicates and delivers the Core adoption path; it is not a
survey, telemetry plan, market-size estimate, or evidence of broad adoption.

Primary question:

> Can a first-time user understand the local control-plane boundary, inspect the
> proposed repository changes, initialize safely, and identify the next useful
> action without the maintainer teaching the product vocabulary?

Council is secondary. The study checks only whether participants understand
that it is opt-in, experimental, and advisory. It does not ask them to run a
real provider, use a paid service, or authorize network execution.

## Participant mix

Recruit three people who have not used Project Loop Harness or read its docs.
Record experience as context, not as a screening score.

| Participant | Desired perspective | Minimum context |
| --- | --- | --- |
| P1 | Frequent coding-agent operator | Uses Codex, Claude Code, or an equivalent tool in repositories |
| P2 | Software engineer with occasional agent use | Comfortable with Git and a terminal |
| P3 | Maintainer or technical lead | Reviews others' changes, evidence, or release readiness |

Do not describe these three people as representative of all developers. If the
available mix differs, record the actual mix rather than relabeling people.

## Materials and safety

- A clean disposable repository containing a tiny documented Python project.
- A machine with Python 3.10+ and `pipx`, or a disposable virtual environment.
- The public v0.5.0 PyPI package, GitHub README, and Adoption Guide.
- Screen and audio recording only with explicit consent; otherwise use observer
  notes and timestamps.
- No employer repository, credentials, secrets, production data, paid provider,
  or externally visible write.
- A reset copy of the scratch repository for each participant.

Before the session, verify that the package and URLs in
[launch-checklist.md](launch-checklist.md) still resolve. Do not pre-initialize
the participant's copy.

## Session format (45–55 minutes)

### 1. Introduction and consent — 3 minutes

Read this neutral script:

> We are evaluating the product and its documentation, not you. Please think
> aloud. I will usually wait when you are stuck so we can observe the problem.
> You may stop at any time. Do not enter credentials or use a real project.

Record consent mode and whether recording is allowed. Assign only `P1`, `P2`,
or `P3` in the study notes.

### 2. Thirty-second comprehension — 3 minutes

Show only the GitHub repository landing page. After 30 seconds, hide it and ask:

1. What do you think this tool is for?
2. Who would use it?
3. What would it change or store?
4. What would you try first?

Do not correct the participant yet. Record their words and any incorrect claims.

### 3. Inspect-first adoption task — 12 minutes

Give this task without command hints:

> Evaluate whether you would add Project Loop Harness v0.5.0 to this existing
> scratch repository. Inspect the proposed changes before applying them. Tell me
> what you expect to change and what you expect to remain local.

The participant may use the README and Adoption Guide. Observe whether they:

- find an installation route;
- run `pcl init --dry-run --json` before `pcl init`;
- distinguish create/update/skip/overwrite outcomes;
- notice the existing-instruction and `pcl.yaml` preservation boundary;
- identify `.project-loop/project.db` as local state;
- avoid `--force`, or explain why it requires review.

If there is no progress for three minutes, ask, “What information are you
looking for?” This is a probe, not a solution. After five minutes on the same
blocker, provide the smallest hint and mark the task `assisted`.

### 4. Initialize and find first value — 12 minutes

Give this task:

> Apply the inspected plan to the scratch repository, check whether the harness
> is healthy, and show me the first output that would help you supervise an
> agent's work.

Observe the path through `pcl init`, `pcl doctor`, `pcl validate --strict`, and
`pcl render --json`. The exact command order is less important than whether the
participant can explain:

- which artifact is authoritative current state;
- why JSONL exists;
- why generated HTML is not machine state;
- what evidence would support a future “done” claim;
- when an agent should stop for a human.

Ask the participant to point to their “first useful output.” Do not choose it
for them.

### 5. Boundary check — 7 minutes

Show the README's Council Profile section and ask:

1. Is Council required for a normal, clear task?
2. Does Council execute a provider or approve a decision?
3. Where would real network or paid execution happen?
4. Who authorizes a proposed choice?

The correct boundary is: Council is opt-in/experimental and advisory; Direct is
the default; real provider execution is outside Core; human authority is not
manufactured by Council output.

### 6. Debrief — 8 minutes

Ask in this order:

1. What was the first moment the tool became useful?
2. What was the first moment you were unsure what to do?
3. Which term was hardest to understand?
4. What did you expect the tool to automate that it did not?
5. What did it automate that you expected to control yourself?
6. What, if anything, made the local-state boundary trustworthy?
7. What would stop you from trying it on a small real repository?
8. Would you use it with one agent, across agents, or not at all? Why?
9. What is the one change that would most improve the first ten minutes?

End by explaining any boundary the participant misunderstood. Do not turn the
debrief into a sales pitch.

## Measurement sheet

Record raw observations per participant before synthesizing themes.

| Metric | Definition | Value |
| --- | --- | --- |
| `value_explanation_30s` | Accurate / partial / inaccurate after 30 seconds | |
| `time_to_dry_run_sec` | From task start to completed dry run | |
| `dry_run_boundary` | Correct / partial / incorrect explanation | |
| `init_completion` | Unassisted / assisted / not completed | |
| `time_to_first_value_sec` | From adoption task start to participant-named useful output | |
| `first_value_artifact` | Participant's words and artifact/command | |
| `first_blocker` | Timestamp, action, expectation, observed result | |
| `hints_count` | Number and exact content of moderator hints | |
| `core_state_model` | Correctly distinguishes SQLite / JSONL / HTML: yes / partial / no | |
| `human_gate_model` | Names at least one genuine human decision and no unsafe auto-action | |
| `council_boundary` | All four boundary questions correct: yes / partial / no | |
| `trust_score` | 1–5 after use; capture reason verbatim | |
| `try_intent` | Yes / maybe / no for a small real repo; capture condition | |

For each observed issue, also record:

```text
Observation ID:
Participant:
Timestamp:
Task:
Expected by participant:
Observed:
Verbatim quote:
Assistance given:
Severity: blocker | major | minor | note
Candidate change:
Evidence link or screenshot:
```

## Adoption and revision criteria

With only three participants, use these as go/no-go signals for another
iteration, not statistical proof.

### Accept the Core first-use path for a wider feedback round when

- all 3 avoid destructive or external actions and do not treat generated HTML
  as the system of record;
- at least 2 of 3 accurately explain the product after 30 seconds;
- at least 2 of 3 complete dry-run and initialization without a command-level
  hint;
- all 3 can identify what the dry run would change before applying it;
- at least 2 of 3 identify a useful output within 10 minutes of starting the
  adoption task;
- all 3 understand Council is optional/advisory and Direct remains the default;
- no unresolved blocker is shared by 2 or more participants.

### Revise before a wider feedback round when

- any participant believes `pcl init` enables telemetry, cloud sync, provider
  execution, or automatic GitHub writes;
- any participant treats Council output as approval or assumes Council is
  required for clear work;
- 2 or more participants cannot explain the dry-run boundary;
- 2 or more participants need the same moderator hint;
- median time to participant-named first value exceeds 10 minutes;
- a participant reaches for `--force` without recognizing replacement risk;
- documentation and observed CLI behavior disagree.

One safety misunderstanding is enough to block the affected claim or workflow
from launch copy until corrected. Minor terminology friction becomes a ranked
follow-up issue rather than an automatic stop.

## Synthesis and decision

After all three sessions:

1. Preserve the three raw sheets separately.
2. Cluster observations by comprehension, install, inspect, initialize, first
   value, state model, human gate, and Council boundary.
3. Rank repeated blockers before isolated preferences.
4. Map every proposed copy/product change to observation IDs.
5. Mark each candidate `adopt`, `defer`, or `reject`, with the criterion and
   human owner.
6. Have a human approve any public claim derived from the study.

Do not convert three sessions into user-count, conversion-rate, market, or
competitor claims. Report counts as “2 of 3 study participants” with the study
date and recruitment context.
