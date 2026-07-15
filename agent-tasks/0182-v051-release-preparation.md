# 0182: v0.5.1 local release preparation

- **Status:** Done
- **Milestone:** v0.5.1 Trace & Efficient Handoff
- **Priority:** P1
- **Size:** M
- **Dependency:** 0181 controlled evaluation with human `continue`
- **DB schema:** remains 8 unless separately approved earlier

## Goal

Prepare a trustworthy local v0.5.1 release candidate after the frozen Trace
evaluation satisfies the milestone gate.

## Scope

1. Align package, CLI, MCP, release notes, task indexes, and contract-version
   documentation on v0.5.1.
2. Run targeted Trace tests, full lint/test, strict validation, and render after
   the final tracked edit.
3. Build fresh wheel and sdist artifacts and verify packaged contracts,
   fixtures, docs, and clean-install behavior.
4. Run a scratch init/context/resume smoke proving valid, invalid, and no-index
   paths from installed artifacts.
5. Record hashes, evaluation evidence, compatibility, and residual risk in the
   local release handoff.

## Invariants

- No tag, push, GitHub Release, PyPI write, pipx upgrade, or launch post.
- No threshold waiver or removal of failed evaluation cases.
- Council remains opt-in and provider execution remains outside Core.

## Acceptance

1. All v0.5.1 source/package surfaces agree.
2. Source, wheel, and sdist smokes pass for valid, invalid-binding, and no-index
   handoffs.
3. Full QA and clean-install checks pass with reviewable output.
4. Artifact hashes and residual limitations are recorded.
5. An independent reviewer approves or returns bounded findings.

## Non-goals

- Publication or external announcement.
- External-user adoption claims.

## Completion evidence

- Evidence `E-0438` preserves the local handoff, independent Codex approval,
  wheel, and sdist as byte-identical copied members.
- Final repository QA: 1039 passed, 1 skipped; Ruff passed; strict validation
  reported 0 errors; render passed.
- Publication remains a separate human decision.
