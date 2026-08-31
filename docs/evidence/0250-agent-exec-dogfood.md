# 0250 — Project-agnostic `pcl exec` dogfood closeout

**Verified:** 2026-08-31

**Outcome:** Accepted for explicit use and ready for the separate cross-agent
policy/audit rollout in GitHub Issue #13. The runtime implementation from
GitHub Issue #8 is merged on `main`, exact-commit CI is green, and real Python
and Node/TypeScript repositories both returned truthful bounded results with no
observed false classification.

**Candidate:** `df94bf9c5315f92cbc0847b72e074d89dd2d786b`

**Source chain:**

- implementation PR: <https://github.com/mocchalera/project-loop-harness/pull/12>
- implementation HEAD: `db3d5dc95e78cdae42b388886a39dda93c66a1c9`
- merge commit: `df94bf9c5315f92cbc0847b72e074d89dd2d786b`
- exact-merge main CI: <https://github.com/mocchalera/project-loop-harness/actions/runs/33344792547>

The main CI run completed successfully across Python 3.10, 3.11, 3.12, and
3.13, MCP conformance on Ubuntu and Windows, and the Windows CLI smoke job.

## Frozen protocol

The dogfood used the merged `pcl exec` runtime directly. No per-repository
wrapper was introduced.

```bash
pcl --json exec -- <verification argv...>
```

For each successful run, the observation recorded:

- the frozen repository commit;
- the exact argv family;
- child exit and typed status;
- raw stdout + stderr bytes;
- agent-facing exposed bytes and lines;
- reduction ratio;
- bounded diagnostic follow-up count;
- false-classification count.

Raw terminal output was not committed. The JSON result artifacts were retained
only as bounded GitHub Actions artifacts for the referenced runs.

## Results

| Repository family | Frozen repository / command | Result | Raw bytes | Exposed | Reduction | Diagnostic follow-ups | False classifications |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| Python test suite | `mocchalera/project-loop-harness@df94bf9` — `pytest` | `PASS`, exit 0 | 13,399 | 89 bytes / 1 line | 99.3358% | 0 | 0 |
| Python package build | `mocchalera/project-loop-harness@df94bf9` — `python -m build` | `PASS`, exit 0 | 167,873 | 87 bytes / 1 line | 99.9482% | 0 | 0 |
| Node/TypeScript verification | `mocchalera/agi-cockpit-mcp@9fa0e5f` — `npm run verify:full` | `PASS`, exit 0 | 81,201 | 87 bytes / 1 line | 99.8929% | 0 | 0 |

### Python full-suite observation

- run: <https://github.com/mocchalera/project-loop-harness/actions/runs/33345757575>
- artifact: <https://github.com/mocchalera/project-loop-harness/actions/runs/33345757575/artifacts/9742226015>
- `pcl exec` run ID: `AX-20260831T005042Z-1752deed6720`
- duration: 1,163,481 ms
- stdout: 13,399 bytes
- stderr: 0 bytes
- diagnostics: unavailable, as expected for `PASS`
- output truncation: false

The full project test suite completed through the guarded runtime with the
original exit code preserved and no extra diagnostic read.

### Python build observation

- run: <https://github.com/mocchalera/project-loop-harness/actions/runs/33345619540>
- artifact: <https://github.com/mocchalera/project-loop-harness/actions/runs/33345619540/artifacts/9741881727>
- `pcl exec` run ID: `AX-20260831T004749Z-0f80c78ae327`
- duration: 6,519 ms
- stdout: 156,243 bytes
- stderr: 11,630 bytes
- diagnostics: unavailable, as expected for `PASS`
- output truncation: false

### Node/TypeScript observation

- run: <https://github.com/mocchalera/agi-cockpit-mcp/actions/runs/33344989656>
- artifact: <https://github.com/mocchalera/agi-cockpit-mcp/actions/runs/33344989656/artifacts/9741695866>
- target commit: `9fa0e5f61559c12fb7a99e05b01df9c164726f80`
- `pcl exec` run ID: `AX-20260831T003501Z-b379c73ad25a`
- duration: 19,845 ms
- stdout: 81,201 bytes
- stderr: 0 bytes
- diagnostics: unavailable, as expected for `PASS`
- output truncation: false

The Node repository exercised its existing `verify:full` chain rather than a
synthetic output fixture.

## Protocol corrections and bounded failure diagnosis

Two setup defects were encountered and retained as evidence rather than hidden.
Neither was a `pcl exec` classification defect.

### Private-repository checkout boundary

The first Node attempt was launched from the public Project Loop Harness
repository and failed before `pcl exec` because that workflow token could not
checkout the private `agi-cockpit-mcp` repository. The protocol was corrected by
running the dogfood workflow inside the private target repository at its frozen
commit. No failed command result was reclassified as success.

### Shallow Git history

The first full Python-suite attempt used `fetch-depth: 1`. A frozen layered
ablation test requires historical commit `7fa22b2`, so `pytest` correctly failed
with child exit 1 and `pcl exec` returned typed `FAIL`.

A bounded diagnostic rerun used one explicit:

```bash
pcl exec show <run-id> --errors
```

That single read exposed the exact `git rev-parse 7fa22b2` failure without
requiring the raw test log. The diagnostic run reported:

- raw bytes: 12,086;
- exposed bytes: 2,267 across 27 lines;
- reduction: 81.2428%;
- follow-up reads: 1;
- false classifications: 0.

Run and artifact:

- <https://github.com/mocchalera/project-loop-harness/actions/runs/33345436641>
- <https://github.com/mocchalera/project-loop-harness/actions/runs/33345436641/artifacts/9741906742>

The protocol was then corrected to fetch full history. The unchanged merged
runtime and unchanged full `pytest` command passed, producing the accepted
Python observation above. The original failure remains part of this record and
was not overwritten by the later success.

## Security and authority observations

Observed behavior remained inside the task 0228 boundary:

- no `.project-loop` lifecycle state was required for command execution;
- no Goal, Task, Evidence, completion, proof, or publication authority was
  created;
- no raw stdout or stderr was projected into GitHub Issues or committed docs;
- PASS runs stored no diagnostic body;
- all public summaries used typed status, counts, and opaque run IDs;
- no automatic retry occurred;
- the initial failure remained distinguishable from the corrected later run;
- no false PASS or false FAIL was observed in the accepted runs.

Redaction remains defense in depth, not a claim that arbitrary external command
output is inherently secret-free.

## Decision

**Accept the project-agnostic runtime and proceed to a separate staged rollout.**

GitHub Issue #13 owns the next work:

1. one canonical command-classification policy;
2. one shared `agent-output-budget` Skill;
3. deterministic Codex, Claude Code, Gemini CLI, OpenCode, and AGI Cockpit
   projections;
4. inspect-first, reversible host installers;
5. audit-only hooks and measured cross-host sessions.

This decision does **not** authorize automatic command rewriting, broad shell
aliases, command blocking, or raw-log transport. Automatic rewriting requires a
separate Issue and explicit human authorization after audit evidence. No claim
is made that the maintainer's whole development environment is already
configured; actual local host files must still be installed and read back under
Issue #13.
