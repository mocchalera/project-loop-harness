# 0247 v0.6.0 proof-gated release preparation

**Recorded:** 2026-08-11

**Worktree:** `codex/plh-mutation-tail-p0a-20260730`

**Source milestone:** `a622dcabaec8797e05f7060c5b27a3b52903204f`

## Outcome boundary

The concrete runner-observability, process-group authority, proof-workspace
provenance, Evidence presentation, and suite-duration defects have bounded
repairs with targeted green coverage. This record does not claim release:
post-repair full-suite, current-proof, PCL close, final package, remote CI,
tag, GitHub Release, PyPI, and public-install gates remain mandatory.

## RED evidence

- The first fresh source suite on milestone `d7158744` completed in 1665.39s
  with `1 failed, 1920 passed, 2 skipped`. The exact failure was
  `test_resume_restart_context_is_fresh_session_executable_from_public_commands`:
  public `evidence show` returned an internal runner-authority summary body
  containing `stdout_eof`.
- Four call-shape tests then failed before the performance change, proving
  separate Git commands for source snapshot, sealed-workspace checkpoint,
  exact diff commit resolution, and verification root/HEAD observation.
- A representative proof-reuse profile measured 398 Git runner calls and
  8.01s; 7.29s was subprocess work and 5.95s was poll wait.

## GREEN evidence

- The resume/Evidence/runner-authority regression group: 23 passed.
- Proof workspace/admission/authority/manifest plus Evidence boundaries:
  160 passed.
- Proof reuse/anchor/drift/execution: 148 passed in 336.18s.
- Finish/progress/workspace, Goal close routing, runner authority/receipt/
  observability, and guarded process: 137 passed in 56.86s.
- The representative proof-reuse profile now measures 261 Git runner calls
  and 3.93s.
- Ruff, compileall, and `git diff --check` pass for the repair milestone.

Counts overlap and are not summed as unique full-suite coverage. No test was
skipped, excluded, or semantically weakened to reduce duration. Historical
E-0086/E-0088 and unregistered E-0091 remain incomplete provenance only.

## Publication boundary

No push, tag, GitHub Release, PyPI upload, pipx change, deployment, or external
announcement has occurred at this point. Publication is authorized only after
all remaining gates in task 0226 are green.
