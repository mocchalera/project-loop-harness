# Golden Path

This document is the first end-to-end operator path for Project Loop Harness.

It assumes `pcl` is installed from this repository:

```bash
python -m pip install -e '.[dev]'
```

If you are installing the harness into another repository for the first time,
start with [adoption-guide.md](adoption-guide.md). It covers distribution
options, target-project initialization, commit boundaries, and first-prompt
templates.

## 1. Create A Demo Project

```bash
rm -rf /tmp/pcl-demo
mkdir -p /tmp/pcl-demo

pcl init --target /tmp/pcl-demo
pcl doctor --root /tmp/pcl-demo
```

Expected checkpoint:

- `/tmp/pcl-demo/.project-loop/project.db` exists;
- `/tmp/pcl-demo/.project-loop/events.jsonl` exists;
- `pcl doctor --root /tmp/pcl-demo` prints `OK`.

## 2. Start A Goal And Workflow

```bash
pcl goal create --root /tmp/pcl-demo --title "Reach basic feature coverage"
pcl loop run --root /tmp/pcl-demo feature_coverage --goal G-0001
pcl next --root /tmp/pcl-demo --json
```

Expected checkpoint:

- goal `G-0001` is open;
- workflow run `WR-0001` exists;
- jobs `J-0001`, `J-0002`, and `J-0003` are queued;
- `pcl next --json` returns `continue_workflow`.

## 3. Complete The Agent Jobs

```bash
pcl jobs read --root /tmp/pcl-demo J-0001
pcl jobs complete --root /tmp/pcl-demo J-0001 --summary "Mapped project surfaces"
pcl jobs complete --root /tmp/pcl-demo J-0002 --summary "Wrote user stories"
pcl jobs complete --root /tmp/pcl-demo J-0003 --summary "Designed test cases"
pcl next --root /tmp/pcl-demo --explain
```

Expected checkpoint:

- all jobs are terminal and passed;
- `pcl next --explain` says the next action is `record_verification`.

## 4. Verify, Complete, And Close

```bash
pcl verification record --root /tmp/pcl-demo --run WR-0001 --result approved --reason "Reviewed generated coverage"
pcl loop complete --root /tmp/pcl-demo WR-0001 --summary "Feature coverage complete"
pcl goal close --root /tmp/pcl-demo G-0001 --summary "Coverage goal done" --verification V-0001
```

Expected checkpoint:

- workflow run `WR-0001` is passed;
- goal `G-0001` is closed;
- the audit log contains `verification_recorded`, `workflow_run_completed`, and `goal_closed`.

## 5. Validate And Render

```bash
pcl validate --root /tmp/pcl-demo --strict
pcl report goal --root /tmp/pcl-demo G-0001
pcl report run --root /tmp/pcl-demo WR-0001
pcl feature list --root /tmp/pcl-demo --json
pcl render --root /tmp/pcl-demo
```

Review:

- `/tmp/pcl-demo/.project-loop/reports/goal-G-0001.md`;
- `/tmp/pcl-demo/.project-loop/reports/run-WR-0001.md`;
- `pcl feature list --json` can be used to inspect tracked feature IDs and status;
- `/tmp/pcl-demo/.project-loop/dashboard/dashboard.html` for human review;
- `/tmp/pcl-demo/.project-loop/dashboard/dashboard-data.json` for rendered machine context.

If validation fails or the generated artifacts do not match state, follow [recovery-playbook.md](recovery-playbook.md) before continuing.

Status transitions are idempotent for exact same-state requests: repeating a goal, feature, test case, or task status command for the current status exits 0, returns `changed: false` in JSON, and records no new evidence or audit event.

## Executor Smoke Path

Freshly initialized projects include a command-only workflow for dogfooding the
guarded executor:

```bash
pcl workflow verify --root /tmp/pcl-demo --template executor_smoke
pcl workflow sandbox --root /tmp/pcl-demo --template executor_smoke --json
pcl loop execute --root /tmp/pcl-demo executor_smoke --json
pcl validate --root /tmp/pcl-demo --strict
```

Expected checkpoint:

- `pcl workflow verify` reports no errors;
- sandbox output has `blocked_command_count: 0`;
- `pcl loop execute` returns `workflow-executor/v1`;
- the executor records workflow execution evidence, an approved verification,
  and a passed workflow run;
- strict validation passes after execution.

If an executor run fails or is interrupted, let `pcl next` route recovery:

```bash
pcl next --root /tmp/pcl-demo --json
pcl loop execute --root /tmp/pcl-demo workflow_id --retry WR-0001
pcl loop execute --root /tmp/pcl-demo workflow_id --resume WR-0001
```

Retry creates a new linked run. Resume continues an active run without creating
a new run.

## Human Decision Branch

If verification needs human judgment, record it explicitly:

```bash
pcl verification record --root /tmp/pcl-demo --run WR-0001 --result needs_human --reason "Product decision required"
pcl next --root /tmp/pcl-demo --json
```

Then create durable escalation and decision state:

```bash
pcl escalation open --root /tmp/pcl-demo --run WR-0001 --severity high --question "What should ship?" --recommendation "Choose the safest reversible path"
pcl decision open --root /tmp/pcl-demo --escalation ESC-0001 --question "Which path should we take?" --recommendation "Choose the safest reversible path"
pcl decision resolve --root /tmp/pcl-demo DEC-0001 --selected-option "Ship locally first" --reason "Risk stays local"
pcl escalation resolve --root /tmp/pcl-demo ESC-0001 --decision DEC-0001 --summary "Human decision recorded"
```

The linked decision is stored in `decisions.blocks_json`, and `escalation_resolved` records `decision_id` in its event payload.

## Guided Next Action Schema

Every `pcl next --json` action includes:

- `type`;
- `command`;
- `reason`;
- `target`;
- `priority`;
- `blocking`;
- `requires_human`;
- `safe_to_run`;
- `run_policy`;
- `human_guidance`;
- `expected_after`.

Use `pcl next --strict --json` before continuing when you want strict validation failures to take priority over normal loop routing.

Interpret the routing fields this way:

- `safe_to_run: true` means an agent or automation may run the command in the
  current project context.
- `safe_to_run: false` means the command mutates durable loop state or resolves
  a human/terminal decision. It is not necessarily dangerous, but it should not
  be auto-run blindly.
- `requires_human: true` means a person should choose, verify, or confirm the
  transition before it is recorded.
- `blocking: true` means normal loop continuation should wait until the action
  is resolved.

Verification results should be used consistently:

- `approved`: enough evidence exists to complete or close the workflow state;
- `needs_human`: product, UX, data, permission, rollout, or acceptance ambiguity
  requires a durable escalation/decision;
- `inconclusive`: evidence is insufficient or the result cannot be determined
  yet, but no human decision is the direct blocker;
- `rejected`: the workflow result is known to be wrong or unacceptable.

## Checkpoint Reviews

Project Loop is intentionally good at small verified steps. After several
features, pause and review whether those small steps are still moving the larger
product goal forward:

```bash
pcl checkpoint status --root /tmp/pcl-demo --json
pcl checkpoint record --root /tmp/pcl-demo \
  --review-type integration \
  --summary "Reviewed commit boundary, UX checklist, and next priority" \
  --evidence "Reviewed validation output, git diff, UX checklist, and next feature priority"
```

When five features have been marked `done` since the latest checkpoint,
`pcl next --json` returns `checkpoint_review` before it recommends another
feature coverage run. Recording the checkpoint stores `checkpoint_review`
evidence and a `checkpoint_recorded` event, then normal routing resumes.
