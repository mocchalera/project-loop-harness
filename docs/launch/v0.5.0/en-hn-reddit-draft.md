# English launch drafts for HN and Reddit

> Editorial note: Draft only. Complete [launch-checklist.md](launch-checklist.md)
> and obtain human approval for the final channel, title, body, and timing before
> posting.

> **Hacker News compliance stop (checked 2026-07-14):** Hacker News now says,
> "Don't post generated text or AI-edited text." The HN title candidates and
> body below were prepared with AI assistance and therefore **must not be
> submitted or adapted for submission**. They remain only as an internal record
> of the abandoned draft. The human poster must write any HN title and text from
> scratch without using this copy; see [hn-human-authoring-brief.md](hn-human-authoring-brief.md).

## Title candidates

### Hacker News

1. `Show HN: Project Loop Harness – a local control plane for coding-agent work`
2. `Show HN: Turn a coding agent's “done” into evidence and resumable state`
3. `Show HN: A model-neutral, local state machine for supervising coding agents`

### Reddit

1. `I built a local, model-neutral control plane for coding-agent work (v0.5.0)`
2. `Project Loop Harness v0.5.0: evidence-backed state and human gates for coding agents`
3. `Looking for feedback on a local CLI for resumable, auditable agent workflows`

## Hacker News body

I built Project Loop Harness (`pcl`) because coding agents can produce changes,
but their “done” often does not survive a new session, a different model, or a
careful review.

`pcl` is a local control plane and guarded state machine for agentic project
work. SQLite is the system of record, JSONL is an auditable event projection,
and generated HTML is a human review surface. Tests, artifacts, reviews, and
completion packets can be attached as Evidence. State changes go through the
CLI, and the loop stops at decisions that require human authority.

The runtime does not call an LLM and is not tied to one agent vendor. Core is
local-only by default, has no runtime dependencies in v0.5.0, and does not
enable telemetry, cloud sync, provider calls, or automatic GitHub writes.

Quick start:

```bash
pipx install project-loop-harness
cd /path/to/your-project
pcl init --dry-run --json
pcl init
pcl doctor
pcl validate --strict
pcl render --json
```

For an existing repository, the dry run shows what would be created, updated,
or skipped. Normal initialization preserves existing `AGENTS.md`, `CLAUDE.md`,
`.gitignore`, and an existing `pcl.yaml`; template replacement via `--force` is
an explicit review boundary.

v0.5.0 also includes Council Profile, but it is opt-in and experimental. It is
an external advisory boundary for ambiguous or high-risk work—not a provider,
executor, verifier, approval, or replacement for the default Direct path. Real
network or paid-provider execution remains outside Core and requires separate,
hash-bound human authorization.

I am looking for first-use feedback rather than claiming broad adoption. In
particular: Can you explain the value after 30 seconds? Does the init dry run
make the file boundary clear? Where do you first get stuck? Do the agent-safe
and human-decision boundaries match your expectations?

GitHub: https://github.com/mocchalera/project-loop-harness

PyPI v0.5.0: https://pypi.org/project/project-loop-harness/0.5.0/

Release: https://github.com/mocchalera/project-loop-harness/releases/tag/v0.5.0

## Reddit body

I have released v0.5.0 of Project Loop Harness (`pcl`) and would value feedback
from people who supervise coding agents across sessions or model vendors.

The problem I am exploring is not code generation itself. It is preserving what
the agent was asked to achieve, what evidence supports “done,” which risks
remain, whether the next action is safe for an agent, and where a human decision
is required.

The Core is deliberately local and dependency-light:

- SQLite is the current-state system of record.
- JSONL is an append-only audit projection.
- The HTML dashboard is generated for human review, not used as agent state.
- State mutations go through `pcl` and append events.
- The runtime does not call an LLM or enable telemetry/cloud sync/provider calls.
- v0.5.0 declares no runtime dependencies and supports Python 3.10+.

To inspect adoption before changing an existing repo:

```bash
pipx install project-loop-harness
cd /path/to/your-project
pcl init --dry-run --json
```

If the plan looks right, run `pcl init`, tune `pcl.yaml` to the repository's
real checks and permissions, then use `pcl doctor`, `pcl validate --strict`, and
`pcl render --json`.

There is also a Council Profile in v0.5.0. I want to be precise about its status:
it is opt-in and experimental, and its output is advisory Evidence. Direct stays
the default for clear tasks. Council does not approve work or run providers;
real network/paid execution stays outside Core behind separate human
authorization.

I am not presenting user-count or competitor claims. I am specifically trying
to learn whether the first-run experience communicates the boundaries and
delivers value quickly. If you try it in a small scratch repo, I would appreciate
these details:

1. What did you think the tool did before and after the dry run?
2. What was the first useful output?
3. What was the first confusing or blocked step?
4. Which action should have stopped for human review but did not—or vice versa?
5. Would you use this with one agent, across agents, or not at all? Why?

Project: https://github.com/mocchalera/project-loop-harness

PyPI: https://pypi.org/project/project-loop-harness/0.5.0/

Adoption guide: https://github.com/mocchalera/project-loop-harness/blob/main/docs/adoption-guide.md

## Channel adaptation notes

- HN: use one `Show HN` title, keep the body compact, and answer technical
  questions with links to repository contracts rather than adding broad claims.
- Reddit: select the community before posting and adapt the opening sentence to
  its rules. Do not cross-post identical text without checking each community's
  self-promotion policy.
- In both channels, disclose affiliation plainly: the poster is the project
  author/maintainer.
- Do not state download counts, active-user counts, comparative superiority, or
  production readiness unless separately verified and approved at posting time.
